#!/usr/bin/python

# Import the GPIO library and time
import RPi.GPIO as GPIO
import time

# Create timestamp
timestamp = time.strftime("%x") + " " + time.strftime("%X")

# Set our GPIO numbering to BCM
GPIO.setmode(GPIO.BCM)

# Define the GPIO pin that we have our digital output from our sensor connected to, 18 in this case
DO = 18

# Set the GPIO pin to an output
GPIO.setup(DO,GPIO.OUT)

# Print for logging and turn on
print timestamp, "Value:  1"
GPIO.output(DO,GPIO.HIGH)

# Print for logging and turn off
# print timestamp, "Value:  0"
# GPIO.output(DO,GPIO.LOW)
