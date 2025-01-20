from djitellopy import Tello

tello = Tello()

tello.connect()

print(f"배터리 잔량: {tello.get_battery ()} %")

