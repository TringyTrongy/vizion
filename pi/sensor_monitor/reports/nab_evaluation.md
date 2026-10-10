# Detector check on the NAB temperature datasets

Written by `python evaluate.py`.

A window counts as found when an alert starts inside it; any alert that starts outside every window counts as false, although NAB may simply not have labelled some real events. The settings were chosen with `python evaluate.py --sweep` on these same files, so the numbers are optimistic, and they say nothing certain about the DHT11: its profile has to be checked on readings from the real sensor (`python evaluate.py --log <file>`).

All values are in °C, converted from °F. NAB does not state the unit of either file: the office data can only be °F (57–86 °F is 14–30 °C); the machine data is assumed to be °F as well.

### Industrial machine temperature (NAB `machine_temperature_system_failure.csv`)

Settings: Machine temperature: more than 4σ from the average of the last 2 days, a change of more than 11.1 °C within 60 min.

- Labelled windows found: **4 of 4**
- False alerts (starting outside every window): **27** (2.4 per week of data)
- Readings flagged: 2290 of 22695

| Window | Labelled anomaly | Window | Found | First alert in the window |
|---|---|---|---|---|
| 1 | 2013-12-11 06:00 | 12-10 06:25 – 12-12 05:35 | yes | 6.2 h before the labelled time |
| 2 | 2013-12-16 17:25 | 12-15 17:50 – 12-17 17:00 | yes | 20.8 h before the labelled time |
| 3 | 2014-01-28 13:55 | 01-27 14:20 – 01-29 13:30 | yes | 18.8 h before the labelled time |
| 4 | 2014-02-08 14:30 | 02-07 14:55 – 02-09 14:05 | yes | 21.7 h after the labelled time |

### Office ambient temperature (NAB `ambient_temperature_system_failure.csv`)

Settings: Ambient temperature: more than 3σ from the average of the last 14 days.

- Labelled windows found: **2 of 2**
- False alerts (starting outside every window): **7** (0.1 per week of data)
- Readings flagged: 110 of 7267

| Window | Labelled anomaly | Window | Found | First alert in the window |
|---|---|---|---|---|
| 1 | 2013-12-22 20:00 | 12-15 07:00 – 12-30 09:00 | yes | 163.0 h before the labelled time |
| 2 | 2014-04-13 09:00 | 03-29 15:00 – 04-20 22:00 | yes | 3.0 h before the labelled time |
