<template>
  <div class="app-container">
    <el-container>
      <el-header class="header">
        <h1>疲劳操作检测系统</h1>
      </el-header>

      <el-container class="main-content">
        <el-main>
          <el-row :gutter="20">
            <!-- 摄像头画面区域 -->
            <el-col :span="16">
              <el-card class="camera-panel">
                <template #header>
                  <div class="card-header">
                    <span>实时监控</span>
                    <el-button-group>
                      <el-button type="primary" :icon="VideoPlay" @click="startDetection" v-if="!isDetecting">
                        开始检测
                      </el-button>
                      <el-button type="danger" :icon="VideoPause" @click="stopDetection" v-else>
                        停止检测
                      </el-button>
                    </el-button-group>
                  </div>
                </template>
                <div class="camera-container" ref="cameraContainer">
                  <video ref="videoElement" class="camera-feed" autoplay playsinline></video>
                  <canvas ref="canvasElement" class="detection-overlay"></canvas>
                </div>
              </el-card>
            </el-col>

            <!-- 状态监控面板 -->
            <el-col :span="8">
              <el-card class="status-panel">
                <template #header>
                  <div class="card-header">
                    <span>状态监控</span>
                  </div>
                </template>
                <div class="status-content">
                  <div class="status-item">
                    <el-icon>
                      <Warning />
                    </el-icon>
                    <span class="status-label">疲劳状态：</span>
                    <el-tag :type="fatigueStatus === '清醒' ? 'success' : 'danger'">
                      {{ fatigueStatus }}
                    </el-tag>
                  </div>

                  <div class="status-metrics">
                    <el-row :gutter="20">
                      <el-col :span="12">
                        <div class="metric-card">
                          <h3>PERCLOS</h3>
                          <div class="metric-value">{{ (perclosValue * 100).toFixed(1) }}%</div>
                        </div>
                      </el-col>
                      <el-col :span="12">
                        <div class="metric-card">
                          <h3>眨眼频率</h3>
                          <div class="metric-value">{{ blinkFreq.toFixed(2) }}/s</div>
                        </div>
                      </el-col>
                    </el-row>

                    <el-row :gutter="20" style="margin-top: 20px;">
                      <el-col :span="12">
                        <div class="metric-card">
                          <h3>打哈欠次数</h3>
                          <div class="metric-value">{{ yawnCount }}</div>
                        </div>
                      </el-col>
                      <el-col :span="12">
                        <div class="metric-card">
                          <h3>FPS</h3>
                          <div class="metric-value">{{ fps.toFixed(1) }}</div>
                        </div>
                      </el-col>
                    </el-row>
                  </div>

                  <div class="chart-container" ref="chartContainer"></div>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { VideoPlay, VideoPause, Warning } from '@element-plus/icons-vue'
import * as echarts from 'echarts'

// 状态变量
const isDetecting = ref(false)
const fatigueStatus = ref('清醒')
const perclosValue = ref(0)
const blinkFreq = ref(0)
const yawnCount = ref(0)
const fps = ref(0)

// DOM引用
const videoElement = ref(null)
const canvasElement = ref(null)
const cameraContainer = ref(null)
const chartContainer = ref(null)

// 图表实例
let chart = null

// WebSocket连接和状态
const ws = ref(null)
const canvasCtx = ref(null)
const wsReconnectAttempts = ref(0)
const maxReconnectAttempts = 5
const reconnectDelay = 3000

// WebSocket连接管理
const setupWebSocket = () => {
  if (wsReconnectAttempts.value >= maxReconnectAttempts) {
    ElMessage.error('无法连接到服务器，请检查服务器状态后重试')
    stopDetection()
    return
  }

  // 使用当前主机名和动态端口连接WebSocket服务器
  const host = window.location.hostname || 'localhost'
  ws.value = new WebSocket(`ws://${host}:8766`)

  ws.value.onopen = () => {
    console.log('WebSocket连接已建立')
    wsReconnectAttempts.value = 0
    startHeartbeat()
  }

  ws.value.onerror = (error) => {
    console.error('WebSocket错误:', error)
    wsReconnectAttempts.value++
  }

  ws.value.onclose = () => {
    console.log('WebSocket连接已关闭')
    clearInterval(heartbeatInterval)
    if (isDetecting.value) {
      setTimeout(() => setupWebSocket(), reconnectDelay)
    }
  }

  ws.value.onmessage = handleWebSocketMessage
}

// 心跳检测
let heartbeatInterval
const startHeartbeat = () => {
  clearInterval(heartbeatInterval)
  heartbeatInterval = setInterval(() => {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ type: 'ping' }))
    }
  }, 30000)
}

// 处理WebSocket消息
const handleWebSocketMessage = (event) => {
  try {
    const data = JSON.parse(event.data)

    if (data.error) {
      ElMessage.error(data.error)
      return
    }

    updateMetrics(data)
    updateDetectionOverlay(data.detections)
  } catch (error) {
    console.error('处理WebSocket消息时出错:', error)
  }
}

// 更新指标
const updateMetrics = (data) => {
  fatigueStatus.value = data.fatigue_status
  perclosValue.value = data.perclos
  blinkFreq.value = data.blink_freq
  yawnCount.value = data.yawn_count
  fps.value = data.fps

  updateChart(data.perclos)
}

// 更新图表
const updateChart = (perclos) => {
  if (chart) {
    const now = new Date()
    const newData = [...(chart.getOption().series[0].data || []), [now, perclos]]
    while (newData.length > 50) newData.shift()

    chart.setOption({
      series: [{ data: newData }]
    })
  }
}

// 更新检测框
const updateDetectionOverlay = (detections) => {
  console.log('收到检测结果:', detections)  // 添加调试信息
  if (!canvasCtx.value || !detections || detections.length === 0) {
    console.log('无检测结果或画布未准备好')
    return
  }

  const canvas = canvasElement.value
  canvasCtx.value.clearRect(0, 0, canvas.width, canvas.height)

  // 计算视频和Canvas的比例
  const videoWidth = videoElement.value.videoWidth
  const videoHeight = videoElement.value.videoHeight
  const canvasWidth = canvas.width
  const canvasHeight = canvas.height

  // 计算视频在发送到服务器时的缩放和偏移参数
  // 这些参数需要与sendVideoFrame中的计算保持一致
  let destWidth, destHeight, destX, destY
  if (videoWidth > videoHeight) {
    // 宽屏视频
    destWidth = 300
    destHeight = (videoHeight / videoWidth) * 300
    destX = 0
    destY = (300 - destHeight) / 2
  } else {
    // 竖屏视频
    destHeight = 300
    destWidth = (videoWidth / videoHeight) * 300
    destX = (300 - destWidth) / 2
    destY = 0
  }

  // 计算从模型输入尺寸(300x300)到原始视频尺寸的映射比例
  const modelToVideoScaleX = videoWidth / destWidth
  const modelToVideoScaleY = videoHeight / destHeight

  // 计算从原始视频尺寸到Canvas尺寸的映射比例
  const videoToCanvasScaleX = canvasWidth / videoWidth
  const videoToCanvasScaleY = canvasHeight / videoHeight

  detections.forEach(det => {
    console.log('处理检测框:', det)  // 添加调试信息
    const [x1, y1, x2, y2] = det.bbox
    
    // 首先将检测框坐标从模型输入尺寸(300x300)映射回原始视频坐标
    // 需要考虑发送到服务器时的缩放和偏移
    const videoX1 = (x1 - destX) * modelToVideoScaleX
    const videoY1 = (y1 - destY) * modelToVideoScaleY
    const videoX2 = (x2 - destX) * modelToVideoScaleX
    const videoY2 = (y2 - destY) * modelToVideoScaleY
    
    // 然后将原始视频坐标映射到Canvas尺寸
    const canvasX1 = videoX1 * videoToCanvasScaleX
    const canvasY1 = videoY1 * videoToCanvasScaleY
    const canvasX2 = videoX2 * videoToCanvasScaleX
    const canvasY2 = videoY2 * videoToCanvasScaleY
    
    const width = canvasX2 - canvasX1
    const height = canvasY2 - canvasY1

    // 绘制边界框
    canvasCtx.value.strokeStyle = `rgb(${det.color[0]}, ${det.color[1]}, ${det.color[2]})`
    canvasCtx.value.lineWidth = 2
    canvasCtx.value.strokeRect(canvasX1, canvasY1, width, height)

    // 绘制标签
    canvasCtx.value.fillStyle = '#fff'
    canvasCtx.value.font = '14px Arial'
    canvasCtx.value.fillText(
      `${det.label}: ${det.score.toFixed(2)}`,
      canvasX1,
      canvasY1 - 5
    )
  })
}

// 开始检测
const startDetection = async () => {
  try {
    // 获取摄像头权限和视频流
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 640 },    // 改回较高分辨率
        height: { ideal: 480 },
        frameRate: { ideal: 10 }
      }
    })

    videoElement.value.srcObject = stream
    isDetecting.value = true

    // 等待视频元数据加载完成
    await new Promise(resolve => {
      videoElement.value.onloadedmetadata = () => {
        // 设置Canvas尺寸
        canvasElement.value.width = videoElement.value.videoWidth
        canvasElement.value.height = videoElement.value.videoHeight
        // 初始化Canvas上下文
        canvasCtx.value = canvasElement.value.getContext('2d')
        resolve()
      }
    })

    // 初始化WebSocket连接
    setupWebSocket()

    // 开始发送视频帧
    let frameCount = 0
    const targetFPS = 10  // 降低帧率
    const frameInterval = 1000 / targetFPS
    let lastFrameTime = performance.now()

    const sendVideoFrame = async () => {
      if (!isDetecting.value || !ws.value || ws.value.readyState !== WebSocket.OPEN) {
        requestAnimationFrame(sendVideoFrame)
        return
      }

      const now = performance.now()
      const elapsed = now - lastFrameTime

      if (elapsed >= frameInterval) {
        const tempCanvas = document.createElement('canvas')
        // 保持300x300的输入尺寸，与模型期望的输入一致
        tempCanvas.width = 300
        tempCanvas.height = 300
        const tempCtx = tempCanvas.getContext('2d')

        try {
          if (videoElement.value.readyState === videoElement.value.HAVE_ENOUGH_DATA) {
            // 不裁剪视频，而是保持原始宽高比并缩放到300x300
            // 这样可以确保检测框坐标与原始视频匹配
            const videoWidth = videoElement.value.videoWidth
            const videoHeight = videoElement.value.videoHeight
            
            // 计算缩放和居中参数
            let destWidth, destHeight, destX, destY
            
            if (videoWidth > videoHeight) {
              // 宽屏视频
              destWidth = 300
              destHeight = (videoHeight / videoWidth) * 300
              destX = 0
              destY = (300 - destHeight) / 2
            } else {
              // 竖屏视频
              destHeight = 300
              destWidth = (videoWidth / videoHeight) * 300
              destX = (300 - destWidth) / 2
              destY = 0
            }
            
            // 先用黑色填充整个画布
            tempCtx.fillStyle = '#000'
            tempCtx.fillRect(0, 0, 300, 300)
            
            // 绘制视频帧，保持宽高比
            tempCtx.drawImage(
              videoElement.value,
              0, 0, videoWidth, videoHeight,  // 源图像，不裁剪
              destX, destY, destWidth, destHeight  // 目标位置和尺寸
            )

            const blob = await new Promise(resolve => {
              tempCanvas.toBlob(resolve, 'image/jpeg', 0.9)  // 提高图像质量
            })
            ws.value.send(blob)
            frameCount++
            lastFrameTime = now
          }
        } catch (error) {
          console.error('处理视频帧时出错:', error)
        } finally {
          tempCanvas.remove()
        }
      }

      requestAnimationFrame(sendVideoFrame)
    }

    // 开始发送视频帧
    sendVideoFrame()

    // 定期更新FPS
    setInterval(() => {
      fps.value = frameCount
      frameCount = 0
    }, 1000)

  } catch (err) {
    console.error('无法访问摄像头:', err)
    ElMessage.error('无法访问摄像头，请检查权限设置')
    stopDetection()
  }
}

// 停止检测
const stopDetection = () => {
  const stream = videoElement.value.srcObject
  if (stream) {
    stream.getTracks().forEach(track => track.stop())
  }
  videoElement.value.srcObject = null
  isDetecting.value = false

  // 关闭WebSocket连接
  if (ws.value) {
    ws.value.close()
    ws.value = null
  }

  // 清除Canvas
  if (canvasCtx.value) {
    canvasCtx.value.clearRect(0, 0, canvasElement.value.width, canvasElement.value.height)
  }
}

// 初始化图表
const initChart = () => {
  if (chartContainer.value) {
    chart = echarts.init(chartContainer.value)
    const option = {
      title: {
        text: '疲劳指标趋势',
        textStyle: {
          fontSize: 14
        }
      },
      tooltip: {
        trigger: 'axis'
      },
      xAxis: {
        type: 'time',
        axisLabel: {
          formatter: '{HH}:{mm}:{ss}'
        }
      },
      yAxis: {
        type: 'value',
        max: 1,
        min: 0
      },
      series: [
        {
          name: 'PERCLOS',
          type: 'line',
          smooth: true,
          data: []
        }
      ]
    }
    chart.setOption(option)
  }
}

// 生命周期钩子
onMounted(() => {
  initChart()
  window.addEventListener('resize', () => chart?.resize())
})

onUnmounted(() => {
  stopDetection()
  chart?.dispose()
  window.removeEventListener('resize', () => chart?.resize())
})
</script>

<style scoped>
.app-container {
  height: 100vh;
  background-color: #f5f7fa;
}

.header {
  background-color: #fff;
  border-bottom: 1px solid #dcdfe6;
  display: flex;
  align-items: center;
  padding: 0 20px;
}

.header h1 {
  margin: 0;
  font-size: 20px;
  color: #303133;
}

.main-content {
  padding: 20px;
  height: calc(100vh - 60px);
}

.camera-panel,
.status-panel {
  height: calc(100vh - 120px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.camera-container {
  position: relative;
  width: 100%;
  height: calc(100% - 60px);
  background-color: #000;
}

.camera-feed {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.detection-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.status-content {
  height: calc(100% - 60px);
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
}

.status-metrics {
  flex-grow: 1;
}

.metric-card {
  background-color: #f5f7fa;
  border-radius: 8px;
  padding: 15px;
  text-align: center;
}

.metric-card h3 {
  margin: 0 0 10px 0;
  font-size: 14px;
  color: #606266;
}

.metric-value {
  font-size: 24px;
  font-weight: bold;
  color: #303133;
}

.chart-container {
  height: 300px;
  margin-top: auto;
}
</style>