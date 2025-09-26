import asyncio
import websockets
import cv2
import numpy as np
import json
import torch
import torch.nn as nn
import torch.backends.cudnn as cudnn
from detection import Detect
from ssd_net_vgg import SSD
from voc0712 import VOC_CLASSES
import utils
import socket
import sys
import Config as config

# 初始化SSD模型
net = SSD()
net = torch.nn.DataParallel(net)
net.train(mode=False)
try:
    net.load_state_dict(torch.load('./weights/ssd_voc_5000_plus.pth', map_location=lambda storage, loc: storage))
    print("Model loaded successfully")
except Exception as e:
    print(f"Error loading model: {str(e)}")
    sys.exit(1)

if torch.cuda.is_available():
    try:
        # 设置CUDA内存分配策略
        torch.cuda.set_per_process_memory_fraction(0.8)  # 限制GPU内存使用比例
        torch.cuda.empty_cache()  # 清理GPU缓存
        net = net.cuda()
        cudnn.benchmark = True
        print("Using CUDA for inference")
    except Exception as e:
        print(f"Error moving model to CUDA: {str(e)}")
        print("Falling back to CPU")
else:
    print("Using CPU for inference")

img_mean = (104.0, 117.0, 123.0)
colors_tableau = [(214, 39, 40), (23, 190, 207), (188, 189, 34), (188, 34, 188), (205, 108, 8)]

# 用于记录眨眼和打哈欠状态的列表
list_B = np.ones(15)  # 眼睛状态List，根据fps修改
list_Y = np.zeros(50)  # 嘴巴状态list，根据fps修改
list_Y1 = np.ones(5)  # 如果在list_Y中存在list_Y1，则判定一次打哈欠
list_blink = [0] * 60  # 眨眼记录
list_yawn = np.zeros(360, dtype=np.int32)  # 打哈欠记录
blink_count = 0  # 眨眼计数
yawn_count = 0  # 打哈欠计数
blink_freq = 0.5  # 眨眼频率初始值
yawn_freq = 0  # 打哈欠频率初始值

async def process_frame(frame_data):
    try:
        # 确保每次处理前清理GPU缓存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        # 检查输入数据类型
        if frame_data is None:
            print("错误：接收到的数据为空")
            return {
                'error': '数据为空',
                'detections': [],
                'fatigue_status': '未知',
                'perclos': 0,
                'blink_freq': 0,
                'yawn_count': 0,
                'fps': 0
            }
        
        if not isinstance(frame_data, (bytes, bytearray)):
            print(f"错误：接收到的数据类型不正确，期望bytes或bytearray类型，实际接收到{type(frame_data)}类型")
            return {
                'error': '数据类型错误',
                'detections': [],
                'fatigue_status': '未知',
                'perclos': 0,
                'blink_freq': 0,
                'yawn_count': 0,
                'fps': 0
            }
            
        # 将二进制图像数据转换为numpy数组
        try:
            nparr = np.frombuffer(frame_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                print("错误：无法解码图像数据，请检查数据格式是否正确")
                return {
                    'error': '图像解码失败',
                    'detections': [],
                    'fatigue_status': '未知',
                    'perclos': 0,
                    'blink_freq': 0,
                    'yawn_count': 0,
                    'fps': 0
                }
            if len(img.shape) != 3 or img.shape[2] != 3:
                print(f"错误：图像格式不正确，需要3通道RGB图像，当前shape: {img.shape}")
                return {
                    'error': '图像格式错误',
                    'detections': [],
                    'fatigue_status': '未知',
                    'perclos': 0,
                    'blink_freq': 0,
                    'yawn_count': 0,
                    'fps': 0
                }
        except Exception as e:
            print(f"错误：图像数据处理失败 - {str(e)}")
            return {
                'error': f'图像处理错误: {str(e)}',
                'detections': [],
                'fatigue_status': '未知',
                'perclos': 0,
                'blink_freq': 0,
                'yawn_count': 0,
                'fps': 0
            }

        # 图像预处理
        original_height, original_width = img.shape[:2]
        x = cv2.resize(img, (300, 300)).astype(np.float32)
        x -= img_mean
        x = x.astype(np.float32)
        x = x[:, :, ::-1].copy()
        x = torch.from_numpy(x).permute(2, 0, 1)
        xx = x.unsqueeze(0)
        
        if torch.cuda.is_available():
            xx = xx.cuda()

        # 模型推理
        y = net(xx)
        softmax = nn.Softmax(dim=-1)
        detect = Detect(config.class_num, 0, 200, 0.01, 0.45)
        priors = utils.default_prior_box()
        
        loc, conf = y
        loc = torch.cat([o.view(o.size(0), -1) for o in loc], dim=1)
        conf = torch.cat([o.view(o.size(0), -1) for o in conf], dim=1)
        
        detections = detect.forward(
            loc.view(loc.size(0), -1, 4),
            softmax(conf.view(conf.size(0), -1, config.class_num)),
            torch.cat([o.view(-1, 4) for o in priors], dim=0)
        ).data
        
        # 处理检测结果
        global list_B, list_Y, yawn_count, list_blink, list_yawn
        
        flag_B = True  # 是否闭眼的flag
        flag_Y = False  # 张嘴flag
        num_rec = 0  # 检测到的眼睛的数量
        detections_result = []
        
        # 使用与camera_detection.py相同的scale计算方式
        scale = torch.Tensor([original_width, original_height]).repeat(2)
        
        # 修改检测结果处理部分
        for i in range(detections.size(1)):
            j = 0
            while detections[0, i, j, 0] >= 0.4:
                score = detections[0, i, j, 0].item()
                # 使用完整的标签映射
                label_name = VOC_CLASSES[i-1] if i > 0 and i <= len(VOC_CLASSES) else ''
                
                # 获取边界框坐标
                pt = detections[0, i, j, 1:].cpu().numpy()
                
                # 移除大小检查，确保所有检测结果都被处理
                if True:
                    # 使用与camera_detection.py相同的坐标计算方式
                    pt = (detections[0, i, j, 1:] * scale).cpu().numpy()
                    coords = (pt[0], pt[1]), pt[2]-pt[0]+1, pt[3]-pt[1]+1
                    
                    if label_name == 'closed_eye':
                        flag_B = False
                    if label_name == 'open_mouth':
                        flag_Y = True
                    
                    detections_result.append({
                        'label': label_name,
                        'score': float(score),
                        'bbox': [float(pt[0]), float(pt[1]), float(pt[2]), float(pt[3])],
                        'color': list(colors_tableau[i]),
                        'display_txt': '%s:%.2f' % (label_name, score)
                    })
                    print(f"检测结果: 标签={label_name}, 分数={score:.2f}, 坐标=[{pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f}, {pt[3]:.1f}]")
                    j += 1
                    num_rec += 1
                else:
                    break
        
        if num_rec > 0:
            if flag_B:
                list_B = np.append(list_B, 1)
            else:
                list_B = np.append(list_B, 0)
            list_B = np.delete(list_B, 0)
            
            if flag_Y:
                list_Y = np.append(list_Y, 1)
            else:
                list_Y = np.append(list_Y, 0)
            list_Y = np.delete(list_Y, 0)
        
        # 检测眨眼
        # 确保list_B至少有15个元素并进行安全的索引访问
        try:
            if len(list_B) >= 15:
                # 使用负索引来安全访问最后两个元素
                if list_B[-2] == 1 and list_B[-1] == 0:
                    list_blink = np.append(list_blink, 1)
                else:
                    list_blink = np.append(list_blink, 0)
                # 确保list_blink不为空再删除
                if len(list_blink) > 0:
                    list_blink = np.delete(list_blink, 0)
        except Exception as e:
            print(f"警告：眨眼检测过程中出现异常 - {str(e)}")
            # 发生异常时，添加一个默认值以保持数据连续性
            list_blink = np.append(list_blink, 0)
        
        # 检测打哈欠
        # 确保list_Y长度足够进行比较并安全访问
        try:
            if len(list_Y) >= len(list_Y1) and (list_Y[len(list_Y)-len(list_Y1):] == list_Y1).all():
                yawn_count += 1
                list_Y = np.zeros(50)
                # 确保list_yawn不会超出预定大小
                if len(list_yawn) >= 360:
                    list_yawn = np.delete(list_yawn, 0)
                list_yawn = np.append(list_yawn, 1)
            else:
                # 确保list_yawn不会超出预定大小
                if len(list_yawn) >= 360:
                    list_yawn = np.delete(list_yawn, 0)
                list_yawn = np.append(list_yawn, 0)

        except Exception as e:
            print(f"警告：打哈欠检测过程中出现异常 - {str(e)}")
            # 发生异常时，添加一个默认值以保持数据连续性
            if len(list_yawn) >= 360:
                list_yawn = np.delete(list_yawn, 0)
            list_yawn = np.append(list_yawn, 0)
            if len(list_yawn) > 0:
                list_yawn = np.delete(list_yawn, 0)
        
        # 计算疲劳指标
        perclos = 1 - np.average(list_B)
        perblink = np.average(list_blink)
        peryawn = np.average(list_yawn)
        
        # 计算疲劳趋势值
        fatigue_trend = (perclos * 0.5 + (1 - perblink) * 0.3 + peryawn * 0.2)
        
        # 判断疲劳状态
        fatigue_status = '清醒'
        
        # 添加全局帧计数器，用于系统启动稳定期
        global frame_counter
        if 'frame_counter' not in globals():
            frame_counter = 0
        frame_counter += 1
        
        # 系统启动后的前30帧（约3秒）不进行疲劳判断，给系统一个稳定期
        if frame_counter <= 30:
            fatigue_status = '清醒'
        # 使用疲劳趋势值判断
        elif fatigue_trend > 0.6:
            fatigue_status = '疲劳'
        
        return {
            'detections': detections_result,
            'fatigue_status': fatigue_status,
            'perclos': perclos,
            'blink_freq': perblink * 2,  # 转换为每秒频率
            'yawn_count': yawn_count,
            'fps': 30,  # 固定FPS
            'fatigue_trend': float(fatigue_trend)  # 添加疲劳趋势值到返回结果
        }
    except Exception as e:
        print(f"错误：处理帧数据时发生异常 - {str(e)}")
        return None
    finally:
        # 确保在处理完成后释放GPU内存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

async def websocket_handler(websocket, path):
    client_id = id(websocket)
    try:
        print(f"新的WebSocket连接已建立 (ID: {client_id})")
        async for message in websocket:
            try:
                # 检查消息是否为None
                if message is None:
                    print("错误：接收到空消息")
                    await websocket.send(json.dumps({'error': '接收到空消息'}))
                    continue

                # 检查是否是心跳消息或停止检测消息
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        if isinstance(data, dict):
                            if data.get('type') == 'ping':
                                await websocket.send(json.dumps({'type': 'pong'}))
                                continue
                            elif data.get('type') == 'stop':
                                await websocket.close(1000, "Client requested stop")
                                return
                    except json.JSONDecodeError as e:
                        print(f"JSON解析错误: {str(e)}")
                        await websocket.send(json.dumps({'error': 'JSON格式错误'}))
                        continue
                    except Exception as e:
                        print(f"处理字符串消息时发生错误: {str(e)}")
                        await websocket.send(json.dumps({'error': f'处理字符串消息时发生错误: {str(e)}'}))                        
                        continue

                # 处理二进制图像数据
                if isinstance(message, bytes):
                    try:
                        result = await process_frame(message)
                        if result is None:
                            await websocket.send(json.dumps({'error': '处理视频帧失败'}))
                            continue
                        await websocket.send(json.dumps(result))
                    except Exception as e:
                        print(f"处理图像数据时发生错误: {str(e)}")
                        await websocket.send(json.dumps({'error': f'处理图像数据时发生错误: {str(e)}'}))                        
                        continue
                else:
                    print(f"错误：未知的消息类型: {type(message)}")
                    await websocket.send(json.dumps({'error': '未知的消息类型'}))
                    continue

            except websockets.exceptions.ConnectionClosed:
                print(f"客户端连接已关闭 (ID: {client_id})")
                break
            except Exception as e:
                print(f"处理消息时发生错误: {str(e)}")
                try:
                    await websocket.send(json.dumps({'error': str(e)}))
                except:
                    break

    except websockets.exceptions.ConnectionClosed:
        print(f"客户端连接已关闭 (ID: {client_id})")
    except Exception as e:
        print(f"WebSocket处理器发生错误: {str(e)}")
        try:
            await websocket.send(json.dumps({'error': '服务器内部错误'}))
        except:
            pass
    finally:
        print(f"WebSocket连接已终止 (ID: {client_id})")

async def find_free_port(start_port=8766, max_attempts=10):
    """Find a free port starting from start_port"""
    for port in range(start_port, start_port + max_attempts):
        try:
            # Try to create a socket with the current port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('localhost', port))
            sock.close()
            return port
        except OSError:
            continue
    raise OSError(f"Could not find a free port after {max_attempts} attempts")

async def main():
    try:
        # 寻找可用端口
        port = await find_free_port()
        # 配置WebSocket服务器
        server = await websockets.serve(
            websocket_handler,
            '0.0.0.0',  # 允许从任何IP地址访问
            port,
            # 添加必要的协议头和CORS配置
            extra_headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Max-Age': '86400',
            }
        )
        print(f"WebSocket服务器已启动在 ws://localhost:{port}")
        await server.wait_closed()
    except Exception as e:
        print(f"启动服务器时发生错误: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())