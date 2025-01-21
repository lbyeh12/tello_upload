from flask import Flask, render_template, Response, jsonify, request, send_from_directory
from djitellopy import Tello
import speech_recognition as sr
from typing import Dict, Any
import google.generativeai as genai
import os
import json
import time
from dotenv import load_dotenv
import cv2
from queue import Queue
import threading
from gtts import gTTS
import pygame
import tempfile
from PIL import Image

# .env 파일 로드
load_dotenv()

# Gemini API 초기화
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if not GOOGLE_API_KEY:
    raise ValueError(".env 파일에 GOOGLE_API_KEY를 설정해주세요!")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

app = Flask(__name__)

class TelloController:
    def __init__(self):
        self.tello = Tello()
        self.frame_reader = None
        self.is_streaming = False
        self.frame_queue = Queue(maxsize=10)
        self.stream_thread = None
        pygame.mixer.init()
        
    available_functions = {
        "takeoff": {
            "name": "takeoff",
            "description": "드론을 이륙시킵니다",
            "parameters": {}
        },
        "land": {
            "name": "land",
            "description": "드론을 착륙시킵니다",
            "parameters": {}
        },
        "move": {
            "name": "move",
            "description": "드론을 지정된 방향으로 이동시킵니다",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right", "forward", "back"]
                    },
                    "distance": {
                        "type": "integer",
                        "description": "이동 거리 (cm)",
                        "minimum": 20,
                        "maximum": 500
                    }
                },
                "required": ["direction", "distance"]
            }
        },
        "rotate": {
            "name": "rotate",
            "description": "드론을 회전시킵니다",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["clockwise", "counter_clockwise"]
                    },
                    "angle": {
                        "type": "integer",
                        "description": "회전 각도",
                        "minimum": 1,
                        "maximum": 360
                    }
                },
                "required": ["direction", "angle"]
            }
        },
        "scan": {
            "name": "scan",
            "description": "현재 보이는 장면을 촬영하고 분석합니다",
            "parameters": {}
        },
        "start_stream": {
            "name": "start_stream",
            "description": "카메라 스트리밍을 시작합니다",
            "parameters": {}
        },
        "stop_stream": {
            "name": "stop_stream",
            "description": "카메라 스트리밍을 중지합니다",
            "parameters": {}
        }
    }

    def connect(self):
        """드론 연결 및 상태 확인"""
        try:
            if self.is_streaming:
                self.stop_video_stream()
            
            print("드론에 연결 중...")
            self.tello.connect()
            print("✓ 연결 성공!")
            
            battery = self.tello.get_battery()
            print(f"✓ 배터리 잔량: {battery}%")
            
            if battery < 20:
                raise Exception("배터리가 너무 부족합니다")
            
            self.start_video_stream()
            return True
        except Exception as e:
            print(f"연결 오류: {str(e)}")
            raise

    def start_video_stream(self):
        """비디오 스트리밍 시작"""
        if not self.is_streaming:
            self.tello.streamon()
            time.sleep(2)
            self.frame_reader = self.tello.get_frame_read()
            self.is_streaming = True
            
            self.stream_thread = threading.Thread(target=self._stream_loop)
            self.stream_thread.daemon = True
            self.stream_thread.start()
            print("비디오 스트리밍 시작됨")

    def stop_video_stream(self):
        """비디오 스트리밍 중지"""
        print("비디오 스트림 정지 중...")
        self.is_streaming = False
        if self.stream_thread:
            self.stream_thread.join(timeout=2)
        try:
            self.tello.streamoff()
        except:
            pass
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except:
                pass

    def _stream_loop(self):
        """비디오 스트리밍 루프"""
        while self.is_streaming:
            if self.frame_reader:
                frame = self.frame_reader.frame
                if frame is not None:
                    frame = cv2.resize(frame, (640, 480))
                    if self.frame_queue.full():
                        try:
                            self.frame_queue.get_nowait()
                        except:
                            pass
                    try:
                        self.frame_queue.put_nowait(frame.copy())
                    except:
                        pass
            time.sleep(0.03)

    def get_frame(self):
        """현재 프레임 반환"""
        if not self.frame_queue.empty():
            return self.frame_queue.get()
        return None

    def take_photo(self):
        """사진 촬영"""
        if not os.path.exists('photos'):
            os.makedirs('photos')
        
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        filename = f'photos/tello_scan_{timestamp}.jpg'
        
        frame = self.frame_reader.frame
        cv2.imwrite(filename, frame)
        print(f"사진 저장됨: {filename}")
        return filename

    def analyze_image(self, image_path: str) -> str:
        """Gemini Vision으로 이미지 분석"""
        try:
            image = Image.open(image_path)
            response = model.generate_content([
                "이 이미지에서 보이는 것을 자세히 설명해주세요.",
                image
            ])
            return response.text
        except Exception as e:
            print(f"이미지 분석 오류: {str(e)}")
            return f"이미지 분석 중 오류가 발생했습니다: {str(e)}"

    def speak(self, text: str):
        """텍스트를 음성으로 변환하여 재생"""
        try:
            tts = gTTS(text=text, lang='ko')
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
                temp_filename = fp.name
                tts.save(temp_filename)
            
            pygame.mixer.music.load(temp_filename)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            
            os.unlink(temp_filename)
        except Exception as e:
            print(f"TTS 오류: {str(e)}")

    def scan_surroundings(self):
        """현재 보이는 장면을 촬영하고 분석"""
        try:
            print("사진 촬영 중...")
            filename = self.take_photo()
            
            print("이미지 분석 중...")
            analysis = self.analyze_image(filename)
            print(f"분석 결과: {analysis}")
            
            self.speak(analysis)
            
            return filename, analysis
        except Exception as e:
            print(f"스캔 오류: {str(e)}")
            return None, f"스캔 중 오류가 발생했습니다: {str(e)}"

    def execute_function(self, function_name: str, parameters: Dict[str, Any] = None):
        """Function calling 결과를 실제 드론 명령으로 실행"""
        try:
            if function_name == "takeoff":
                print("이륙!")
                return self.tello.takeoff()
                
            elif function_name == "land":
                print("착륙!")
                return self.tello.land()
                
            elif function_name == "move":
                direction = parameters["direction"]
                distance = parameters["distance"]
                print(f"{direction} 방향으로 {distance}cm 이동")
                
                if direction == "up":
                    return self.tello.move_up(distance)
                elif direction == "down":
                    return self.tello.move_down(distance)
                elif direction == "left":
                    return self.tello.move_left(distance)
                elif direction == "right":
                    return self.tello.move_right(distance)
                elif direction == "forward":
                    return self.tello.move_forward(distance)
                elif direction == "back":
                    return self.tello.move_back(distance)
                
            elif function_name == "rotate":
                direction = parameters["direction"]
                angle = parameters["angle"]
                print(f"{direction} 방향으로 {angle}도 회전")
                
                if direction == "clockwise":
                    return self.tello.rotate_clockwise(angle)
                else:
                    return self.tello.rotate_counter_clockwise(angle)
                    
            elif function_name == "scan":
                return self.scan_surroundings()
                
            elif function_name == "start_stream":
                return self.start_video_stream()
                
            elif function_name == "stop_stream":
                return self.stop_video_stream()
                
            time.sleep(1)
            
        except Exception as e:
            print(f"명령 실행 중 오류 발생: {str(e)}")
            raise

def process_voice_command(audio_text: str) -> Dict:
    """음성 명령을 Function calling 형식으로 변환"""
    prompt = """당신은 드론 제어 시스템입니다. 사용자의 한국어 자연어 명령을 드론 제어 명령으로 변환합니다. 반드시 요구된 형식으로 반환해주세요.

가능한 명령어와 형식:
1. 이륙: {"command": "takeoff"}
2. 착륙: {"command": "land"}
3. 이동: {"command": "move", "parameters": {"direction": "[up/down/left/right/forward/back]", "distance": [20-500]}}
4. 회전: {"command": "rotate", "parameters": {"direction": "[clockwise/counter_clockwise]", "angle": [1-360]}}
5. 스캔: {"command": "scan"}
6. 스트리밍 시작: {"command": "start_stream"}
7. 스트리밍 중지: {"command": "stop_stream"}

예시1:
- "주변을 살펴봐" -> {"command": "scan"}
예시2:
- "카메라 켜줘" -> {"command": "start_stream"}
예시3:
- "위로 1미터 올라가줘" -> {"command": "move", "parameters": {"direction": "up", "distance": 100}}
예시4:
- "왼쪽으로 90도 돌아" -> {"command": "rotate", "parameters": {"direction": "counter_clockwise", "angle": 90}}

사용자 명령을 위 JSON 형식으로 변환하여 응답해주세요. 응답은 반드시 유효한 JSON 형식이어야 합니다. 방향이 없을 경우 아무것도 실행하지 않습니다.

사용자 명령: """ + audio_text

    try:
        response = model.generate_content(prompt)
        json_str = response.text[response.text.find("{"):response.text.rfind("}")+1]
        command = json.loads(json_str)
        return command
        
    except Exception as e:
        print(f"Gemini API 오류: {str(e)}")
        raise

# 전역 컨트롤러 인스턴스
controller = None

def generate_frames():
    """비디오 스트림 프레임 생성기"""
    while True:
        if controller and controller.is_streaming:
            frame = controller.get_frame()
            if frame is not None:
                _, buffer = cv2.imencode('.jpg', frame)
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            time.sleep(0.03)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/connect', methods=['POST'])
def connect_drone():
    global controller
    try:
        if controller is None:
            controller = TelloController()
        controller.connect()
        return jsonify({"status": "success", "message": "드론이 연결되었습니다."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/control', methods=['POST'])
def control_drone():
    try:
        if controller:
            command = request.json.get('command')
            params = request.json.get('parameters', {})
            controller.execute_function(command, params)
            return jsonify({"status": "success", "message": "명령이 실행되었습니다."})
        return jsonify({"status": "error", "message": "드론이 연결되지 않았습니다."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/scan', methods=['POST'])
def scan_surroundings():
    try:
        if controller:
            filename, analysis = controller.scan_surroundings()
            return jsonify({
                "status": "success",
                "message": "스캔이 완료되었습니다.",
                "analysis": analysis,
                "image_url": f'/photos/{os.path.basename(filename)}'
            })
        return jsonify({"status": "error", "message": "드론이 연결되지 않았습니다."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/photos/<path:filename>')
def serve_photo(filename):
    return send_from_directory('photos', filename)

def ensure_template_exists():
    """템플릿 디렉토리와 파일이 존재하는지 확인하고 생성"""
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    if not os.path.exists(template_dir):
        os.makedirs(template_dir)
    
    template_path = os.path.join(template_dir, 'index.html')
    if not os.path.exists(template_path):
        html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Tello 드론 제어 시스템</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f0f0f0;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .video-container {
            margin: 20px 0;
            text-align: center;
        }
        .controls {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin: 20px 0;
        }
        button {
            padding: 10px 20px;
            font-size: 16px;
            cursor: pointer;
            background-color: #4CAF50;
            color: white;
            border: none;
            border-radius: 5px;
        }
        button:hover {
            background-color: #45a049;
        }
        button:disabled {
            background-color: #cccccc;
            cursor: not-allowed;
        }
        #status {
            margin: 20px 0;
            padding: 10px;
            border-radius: 5px;
        }
        .success {
            background-color: #dff0d8;
            color: #3c763d;
        }
        .error {
            background-color: #f2dede;
            color: #a94442;
        }
        #analysis {
            margin: 20px 0;
            padding: 15px;
            background-color: #fff;
            border-radius: 5px;
            border: 1px solid #ddd;
        }
        .voice-control {
            margin: 20px 0;
            padding: 15px;
            background-color: #e7f3fe;
            border-radius: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Tello 드론 제어 시스템</h1>
        <div class="video-container">
            <img src="{{ url_for('video_feed') }}" width="640" height="480">
        </div>
        <div class="controls">
            <button onclick="connectDrone()">드론 연결</button>
            <button onclick="scanSurroundings()">주변 스캔</button>
            <button onclick="startVoiceControl()">음성 제어 시작</button>
        </div>
        <div class="voice-control">
            <h2>음성 제어 상태</h2>
            <p id="voiceStatus">음성 제어가 비활성화되어 있습니다.</p>
        </div>
        <div id="status"></div>
        <div id="analysis"></div>
    </div>

    <script>
        let isVoiceControlActive = false;
        let recognition = null;

        function updateStatus(message, isError = false) {
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = message;
            statusDiv.className = isError ? 'error' : 'success';
        }

        function updateAnalysis(text) {
            const analysisDiv = document.getElementById('analysis');
            analysisDiv.textContent = text;
        }

        async function connectDrone() {
            try {
                updateStatus("드론 연결 중...");
                const response = await fetch('/connect', {
                    method: 'POST'
                });
                const data = await response.json();
                updateStatus(data.message, data.status === 'error');
            } catch (error) {
                updateStatus('연결 중 오류가 발생했습니다: ' + error, true);
            }
        }

        async function scanSurroundings() {
            try {
                updateStatus("주변 스캔 중...");
                const response = await fetch('/scan', {
                    method: 'POST'
                });
                const data = await response.json();
                updateStatus(data.message, data.status === 'error');
                if (data.analysis) {
                    updateAnalysis(data.analysis);
                }
            } catch (error) {
                updateStatus('스캔 중 오류가 발생했습니다: ' + error, true);
            }
        }

        function startVoiceControl() {
            if (!isVoiceControlActive) {
                if ('webkitSpeechRecognition' in window) {
                    recognition = new webkitSpeechRecognition();
                    recognition.continuous = true;
                    recognition.lang = 'ko-KR';

                    recognition.onstart = function() {
                        isVoiceControlActive = true;
                        document.getElementById('voiceStatus').textContent = '음성 인식 활성화됨 - 명령을 말씀해주세요';
                    };

                    recognition.onresult = async function(event) {
                        const command = event.results[event.results.length - 1][0].transcript;
                        updateStatus(`인식된 명령: ${command}`);
                        
                        try {
                            const response = await fetch('/control', {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                },
                                body: JSON.stringify({ command: command })
                            });
                            const data = await response.json();
                            updateStatus(data.message, data.status === 'error');
                        } catch (error) {
                            updateStatus('명령 실행 중 오류가 발생했습니다: ' + error, true);
                        }
                    };

                    recognition.onerror = function(event) {
                        updateStatus('음성 인식 오류: ' + event.error, true);
                    };

                    recognition.start();
                } else {
                    updateStatus('이 브라우저는 음성 인식을 지원하지 않습니다.', true);
                }
            } else {
                if (recognition) {
                    recognition.stop();
                    isVoiceControlActive = false;
                    document.getElementById('voiceStatus').textContent = '음성 제어가 비활성화되어 있습니다.';
                }
            }
        }
    </script>
</body>
</html>
"""
        with open(template_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

def main():
    ensure_template_exists()
    app.run(host='0.0.0.0', port=3000, debug=False)

if __name__ == "__main__":
    main()