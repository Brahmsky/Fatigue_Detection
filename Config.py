import torch
import os.path as osp
sk = [ 15, 30, 60, 111, 162, 213, 264 ]#ssd网络先验框尺度参数
feature_map = [ 38, 19, 10, 5, 3, 1 ]#特征图尺寸
steps = [ 8, 16, 32, 64, 100, 300 ]#步长
image_size = 300
aspect_ratios = [[2], [2, 3], [2, 3], [2, 3], [2], [2]]#先验框宽高比
MEANS = (104, 117, 123)#预处理时的均值
batch_size = 8
data_load_number_worker = 0#dataloader线程数
lr = 5e-4
momentum = 0.9#动量
weight_decacy = 5e-4#权值衰减率
gamma = 0.1#学习率衰减率
VOC_ROOT = osp.join('./', "dataset/")
dataset_root = VOC_ROOT
use_cuda = torch.cuda.is_available()
if use_cuda:
    print("Using GPU for training")
    torch.set_default_tensor_type('torch.cuda.FloatTensor')
    torch.cuda.manual_seed(1)  # 设置CUDA随机种子
else:
    print("WARNING: CUDA is not available. Using CPU for training.")
    torch.set_default_tensor_type('torch.FloatTensor')
    torch.manual_seed(1)  # 设置CPU随机种子
lr_steps = (80000, 100000, 120000)#学习率衰减的迭代次数
max_iter = 120000#最大迭代次数
class_num = 5#类别数
