"""
This script explains how to use meteostat for the sake of this project and tests basic library calls.

Refer to https://dev.meteostat.net/overview for in-depth explanations

High level overview of meteostat, it uses stations to get hourly data for a span of time. 
In order to find out the nearest station, enter your geographical point and use the nearest stations function to identify the closest stations.

"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import meteostat as ms


# point is latitude in degrees, longitude in degrees, elevation in meters above sea level, here is an example of ann arbor
POINT = ms.Point(42.2800, -83.7500, 113) 

# the first parameter in datetime is the year, the second is the month, the third is the day, the fourth is the hour etc etc
starting_time = datetime(2018, 1, 1, 0)  # this sets the starting_time to be the first hour of jan 1st 2018
ending_time = datetime(2018, 1, 1, 1)


# Because getting the hourly data for your location requires finding the nearest station, here is how to do that
    # this finds the limit number of nearest stations
nearby_stations = ms.stations.nearby(POINT, limit=4)
# print(nearby_stations)
closest_station_id = nearby_stations.index[0]
print(closest_station_id)
closest_station = ms.Station(id=closest_station_id)


# HERE IS HOW TO ACTUALLY GET THE WEATHER DATA

    # Placing the request requires three parameters
        # the first one is the station that I explained how to get earlier in this file
        # the second and third one is the starting_time and ending_time

    # for each hour within the starting_time and ending_time you will receive values
    # for our purpose we only call values for one hour at a time

ts = ms.hourly(closest_station, starting_time, ending_time)
df = ts.fetch()
print(df)