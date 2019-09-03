import config
import time
import Adafruit_DHT

timestamp = time.strftime("%x") + " " + time.strftime("%X")

# Sensor settings
pin = config.dht_pin
sensor_type = { 'DHT11': Adafruit_DHT.DHT11,
                'DHT22': Adafruit_DHT.DHT22,
                'AM2302': Adafruit_DHT.AM2302 }
sensor = sensor_type[config.dht_sensor]

# Try to grab a sensor reading.  Use the read_retry method which will retry up
# to 15 times to get a sensor reading (waiting 2 seconds between each retry).
humidity, temperature = Adafruit_DHT.read_retry(sensor, pin)

try:
    temperature = temperature * 9.0 / 5.0 + 32
except Exception:
    temperature = -273.15

humidity = humidity * .01

if humidity is not None and temperature is not None:
    print(timestamp, 'Temp: ', temperature, 'Humidity: ', humidity)