import os
import random

"""将数据集按照80%的trainval比例和70%的train比例随机划分,
生成四个txt文件(trainval.txt、test.txt、train.txt和val.txt),
每个文件包含相应图片的索引"""

trainval_percent = 0.8
train_percent = 0.7
xmlfilepath = 'Annotations'
txtsavepath = 'ImageSets\Main'
total_xml = os.listdir(xmlfilepath)

num=len(total_xml)
list=range(num)
tv=int(num*trainval_percent)
tr=int(tv*train_percent)
trainval= random.sample(list,tv)
train=random.sample(trainval,tr)

ftrainval = open('ImageSets/Main/trainval.txt', 'w')
ftest = open('ImageSets/Main/test.txt', 'w')
ftrain = open('ImageSets/Main/train.txt', 'w')
fval = open('ImageSets/Main/val.txt', 'w')

for i in list:
	name=total_xml[i][:-4]+'\n'
	if i in trainval:
		ftrainval.write(name)
	else:
		fval.write(name)	
	if i in train:
		ftrain.write(name)
	else:
		ftest.write(name)

ftrainval.close()
ftrain.close()
fval.close()
ftest .close()