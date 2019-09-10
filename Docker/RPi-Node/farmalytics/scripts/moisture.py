import config
import time
import RPi.GPIO as GPIO

timestamp = time.strftime("%x") + " " + time.strftime("%X")

pin = config.moisture_pin
GPIO.setmode(GPIO.BCM)
GPIO.setup(pin, GPIO.IN)

print(timestamp, 'Value=' + str(GPIO.input(pin)))