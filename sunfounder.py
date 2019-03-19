#!/usr/bin/env python
# This is originally from here - https://github.com/sunfounder/SunFounder_SensorKit_for_RPi2/blob/master/Python/20_photoresistor.py
import PCF8591 as ADC
import RPi.GPIO as GPIO
import time

DO = 17
GPIO.setmode(GPIO.BCM)

def setup():
	ADC.setup(0x48)
	GPIO.setup(DO, GPIO.IN)


def loop():
	status = 1
	while True:
		print 'Value: ', ADC.read(0)
		
		time.sleep(0.2)

if __name__ == '__main__':
	try:
		setup()
		loop()
	except KeyboardInterrupt: 
		pass
