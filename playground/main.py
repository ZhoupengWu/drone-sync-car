from flask import Flask
import time
from djitellopy import Tello

def createTello():
    return Tello()

def moveTello(tello: Tello, command: str):
    match command:
        case "a":
            tello.send_rc_control(-30, 0, 0, 0)
        case "w":
            tello.send_rc_control(0, 30, 0, 0)
        case "s":
            tello.send_rc_control(0, -30, 0, 0)
        case "d":
            tello.send_rc_control(30, 0, 0, 0)
        case "x":
            tello.send_rc_control(0, 0, 0, 0)
        case _:
            pass

tello = createTello()
tello.connect(wait_for_state=False)
time.sleep(3)
print("Batteria: ", tello.query_battery(), "%")

try:
    tello.takeoff()

    while True:
        command = input("Inserisci una lettera: ")

        if command == "q":
            break

        moveTello(tello, command)
finally:
    tello.send_rc_control(0, 0, 0, 0)
    tello.land()
    tello.end()
