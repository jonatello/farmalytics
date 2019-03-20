#!/usr/bin/python

# Edited from this original - https://github.com/modmypi/Moisture-Sensor/blob/master/moisture.py

# Import the GPIO library
import RPi.GPIO as GPIO

# Set our GPIO numbering to BCM
GPIO.setmode(GPIO.BCM)

# Define the GPIO pin that we have our digital output from our sensor connected to, 21 in this case
DO = 21

# Set the GPIO pin to an input
GPIO.setup(DO, GPIO.IN)

# Print the value from the GPIO pin (1 is off, 0 is on/moisture)
print 'Value: ', GPIO.input(DO)
