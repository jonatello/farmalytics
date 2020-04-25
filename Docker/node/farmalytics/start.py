import prometheus_client as prom
import RPi.GPIO as gpio
import Adafruit_DHT as dht
import random
import time
from datetime import datetime
import os
import json
import requests

# DHT sensor settings
dht_pin = os.environ['DHT_PIN']

sensor_name = os.environ['DHT_SENSOR']
sensor_type = {'DHT11': dht.DHT11,
               'DHT22': dht.DHT22,
               'AM2302': dht.AM2302}
dht_sensor = sensor_type[sensor_name]

# OpenWeather settings
OPENWEATHER_URL = 'https://api.openweathermap.org/data/2.5/weather?id=' + os.environ['OW_CITY_ID'] + '&APPID=' + os.environ['OW_API_KEY'] + '&units=imperial'

# Moisture settings
m_pin = int(os.environ['MOISTURE_PIN'])
gpio.setmode(gpio.BCM)
gpio.setup(m_pin, gpio.IN)

if __name__ == '__main__':
    # Instantiate our Prometheus metrics
    humidity = prom.Gauge('farmalytics_humidity', 'Humidity', ['source', 'pin', 'sensor'])
    temperature = prom.Gauge('farmalytics_temperature', 'Temperature', ['source', 'pin', 'sensor'])
    moisture = prom.Gauge('farmalytics_moisture', 'Moisture', ['source', 'pin'])

    # Start the web server
    prom.start_http_server(666)

    while True:
        # Try to grab a sensor reading. Use the read_retry method which will retry up
        # to 15 times to get a sensor reading (waiting 2 seconds between each retry).
        sensor_humidity, sensor_temperature = dht.read_retry(dht_sensor, dht_pin)

        if sensor_temperature:
            sensor_temperature = sensor_temperature * 9.0 / 5.0 + 32
            temperature.labels(source='pi', pin=dht_pin, sensor=sensor_name).set(sensor_temperature)
        else:
            print(datetime.now().strftime("%d/%m/%Y %H:%M:%S") + " Temperature from sensor is null.")

        if sensor_humidity:
            humidity.labels(source='pi', pin=dht_pin, sensor=sensor_name).set(sensor_humidity)
        else:
            print(datetime.now().strftime("%d/%m/%Y %H:%M:%S") + " Humidity from sensor is null.")

        # Get OpenWeather data
        try:
            resp = requests.get(OPENWEATHER_URL)
            if resp.ok:
                response = json.loads(resp.text)
                temperature.labels(source='openweather', pin='openweather', sensor='openweather').set(response['main']['temp'])
                humidity.labels(source='openweather', pin='openweather', sensor='openweather').set(response['main']['humidity'])
        except Exception as e:
            print(datetime.now().strftime("%d/%m/%Y %H:%M:%S") + " Unable to complete OpenWeather API request:")
            print(e)

        # Get moisture
        try:
            if gpio.input(m_pin) == 0:
                moist = 1
            elif gpio.input(m_pin) == 1:
                moist = 0
            moisture.labels(source='garlic', pin=m_pin).set(moist)
        except Exception as e:
            print(datetime.now().strftime("%d/%m/%Y %H:%M:%S") + " Unable to get moisture sensor data:")
            print(e)

        # Pause between each sensor poll
        time.sleep(10)