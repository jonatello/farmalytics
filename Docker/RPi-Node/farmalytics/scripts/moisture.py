import config
import time
import RPi.GPIO as GPIO

timestamp = time.strftime("%x") + " " + time.strftime("%X")

pin = config.moisture_pin
GPIO.setmode(GPIO.BCM)
GPIO.setup(pin, GPIO.IN)

if GPIO.input(pin) == 0:
    moist = 1
elif GPIO.input(pin) == 1:
    moist = 0

print(timestamp, 'Value=' + str(moist))