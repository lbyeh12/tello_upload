from djitellopy import Tello

tello = Tello()

tello.connect()

tello.takeoff()

tello.move_forward(30)

tello.rotate_clockwise(90)

tello.land()