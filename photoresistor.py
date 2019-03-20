#!/usr/bin/env python
# Edited from this original - https://github.com/sunfounder/SunFounder_SensorKit_for_RPi2/blob/master/Python/20_photoresistor.py

# Import the PCF8591 module and GPIO library
import PCF8591 as ADC
import RPi.GPIO as GPIO

# Set our GPIO numbering to BCM
GPIO.setmode(GPIO.BCM)

# Define the GPIO pin that we have our digital output from our sensor connected to, 17 in this case
DO = 17

# Set ADC to a value (?) and the GPIO pin to an input
ADC.setup(0x48)
GPIO.setup(DO, GPIO.IN)

# Print the value from the GPIO pin (255 is off, 0 is on/full sunlight)
print 'Value: ', ADC.read(0)
