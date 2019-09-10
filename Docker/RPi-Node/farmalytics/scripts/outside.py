import config
import json
import time
import requests

timestamp = time.strftime("%x") + " " + time.strftime("%X")

OPENWEATHER_URL = 'https://api.openweathermap.org/data/2.5/weather?id=' + config.ow_city_id + '&APPID=' + config.ow_api_key + '&units=imperial'

resp = requests.get(OPENWEATHER_URL)
if resp.ok:
    response = json.loads(resp.text)
    temperature = response['main']['temp']
    humidity = response['main']['humidity'] * .01
    print(timestamp, 'Temp=' + str(temperature), 'Humidity=' + str(humidity))