import time
import cv2
import os
from threading import Thread
from djitellopy import Tello

# Tello 드론 초기화
tello = Tello()
tello.connect()

# 비행 명령 실행 전에 스트리밍 시작
keepRecording = True
tello.streamon()
time.sleep(2)  # 스트리밍 안정화 시간
frame_read = tello.get_frame_read()

# 비디오 저장 경로 설정
video_path = './video.avi'
if not os.path.exists(os.path.dirname(video_path)):
    os.makedirs(os.path.dirname(video_path))

# 비디오 녹화 함수
def videoRecorder():
    # 카메라에서 프레임 크기 가져오기
    height, width, _ = frame_read.frame.shape
    fps = 30  # FPS 설정

    # VideoWriter 객체 생성
    video = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'XVID'), fps, (width, height))

    while keepRecording:
        frame = frame_read.frame
        if frame is not None:
            video.write(frame)
        else:
            print("Warning: No frame received")  # 프레임이 없을 경우 경고 메시지 출력
        time.sleep(1 / fps)  # FPS 맞추기

    video.release()

# 비디오 녹화 스레드 시작
recorder = Thread(target=videoRecorder)
recorder.start()

# 드론 비행 명령
try:
    tello.takeoff()
    time.sleep(3)  # 안정적으로 이륙 대기
    tello.move_up(100)  # 100cm 상승
    time.sleep(3)
    tello.rotate_counter_clockwise(360)  # 360도 회전
    time.sleep(3)
    tello.land()  # 착륙
    time.sleep(3)
finally:
    # 녹화 종료
    keepRecording = False
    recorder.join()  # 녹화가 완료될 때까지 대기

    # 스트리밍 종료
    tello.streamoff()

print(f"Recording completed and video saved as '{video_path}'")
