import torch
import Config
if Config.use_cuda:
    torch.set_default_tensor_type('torch.cuda.FloatTensor')
else:
    print("WARNING: CUDA is not available. Using CPU for training.")
    torch.set_default_tensor_type('torch.FloatTensor')

import torch.nn as nn
import cv2
import utils
import loss_function
import voc0712
import augmentations
import ssd_net_vgg
import torch.utils.data as data
import torch.optim as optim
from torch.autograd import Variable
import numpy as np
import random

from torchvision import transforms

def adjust_learning_rate(optimizer, gamma, step):
    """Sets the learning rate to the initial LR decayed by 10 at every
        specified step
    # Adapted from PyTorch Imagenet example:
    # https://github.com/pytorch/examples/blob/master/imagenet/main.py
    """
    lr = Config.lr * (gamma ** (step))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr
def detection_collate(batch):
    """Custom collate fn for dealing with batches of images that have a different
    number of associated object annotations (bounding boxes).

    Arguments:
        batch: (tuple) A tuple of tensor images and lists of annotations

    Return:
        A tuple containing:
            1) (tensor) batch of images stacked on their 0 dim
            2) (list of tensors) annotations for a given image are stacked on
                                 0 dim
    """
    targets = []
    imgs = []
    for sample in batch:
        imgs.append(sample[0])
        targets.append(torch.FloatTensor(sample[1]))
    return torch.stack(imgs, 0), targets
def xavier(param):
    nn.init.xavier_uniform_(param)
def weights_init(m):
    if isinstance(m, nn.Conv2d):
        xavier(m.weight.data)
        m.bias.data.zero_()
def train():
    dataset = voc0712.VOCDetection(root=Config.dataset_root,
                           transform=augmentations.SSDAugmentation(Config.image_size,
                                                     Config.MEANS))
    def worker_init_fn(worker_id):
        # 为每个worker设置不同的随机种子
        worker_seed = torch.initial_seed() % 2**32
        # 确保在CPU上生成随机数
        torch.manual_seed(worker_seed)
        np.random.seed(worker_seed)
        random.seed(worker_seed)
    
    data_loader = data.DataLoader(dataset, Config.batch_size,
                              num_workers=Config.data_load_number_worker,
                              shuffle=False, collate_fn=detection_collate,
                              pin_memory=False,
                              worker_init_fn=worker_init_fn)

    net = ssd_net_vgg.SSD()
    vgg_weights = torch.load('./weights/vgg16_reducedfc.pth')

    net.apply(weights_init)
    net.vgg.load_state_dict(vgg_weights)
    if Config.use_cuda:
        net = torch.nn.DataParallel(net)
        net = net.cuda()
    net.train()
    loss_fun = loss_function.LossFun()
    optimizer = optim.SGD(net.parameters(), lr=Config.lr, momentum=Config.momentum,
                          weight_decay=Config.weight_decacy)
    iter = 0
    step_index = 0
    before_epoch = -1
    for epoch in range(2):
        for step,(img,target) in enumerate(data_loader):
            if Config.use_cuda:
                img = img.cuda()
                target = [ann.cuda() for ann in target]
            img = img.float()
            loc_pre,conf_pre = net(img)
            priors = utils.default_prior_box()
            if Config.use_cuda:
                priors = [p.cuda() for p in priors]
            optimizer.zero_grad()
            loss_l,loss_c = loss_fun((loc_pre,conf_pre),target,priors)
            loss = loss_l + loss_c
            loss.backward()
            optimizer.step()
            if iter % 1 == 0 or before_epoch!=epoch:
                print('epoch : ',epoch,' iter : ',iter,' step : ',step,' loss : ',loss.item())
                before_epoch = epoch
            iter+=1
            if iter in Config.lr_steps:
                step_index+=1
                adjust_learning_rate(optimizer,Config.gamma,step_index)
            if iter % 10000 == 0 and iter!=0:
                torch.save(net.state_dict(), 'weights/ssd300_VOC_' +
                           repr(iter) + '.pth')
        if iter >= Config.max_iter:
            break
    torch.save(net.state_dict(), 'weights/ssd_voc_120000.pth')

if __name__ == '__main__':
    train()



