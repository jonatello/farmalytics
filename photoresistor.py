#!/usr/bin/env python
# This is originally from here - https://github.com/sunfounder/SunFounder_SensorKit_for_RPi2/blob/master/Python/20_photoresistor.py
import PCF8591 as ADC
import RPi.GPIO as GPIO

DO = 17
GPIO.setmode(GPIO.BCM)

ADC.setup(0x48)
GPIO.setup(DO, GPIO.IN)

print 'Value: ', ADC.read(0)
