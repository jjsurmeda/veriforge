# Ridgeline R-7 Rolling Stock Interface Specification

> **Fictional evaluation corpus.** Invented for a retrieval benchmark. The
> R-7 specification does not exist and every figure below is deliberately
> different from real-world rolling-stock practice, so an answer drawn from
> engineering knowledge fails the items written against this file. Real-world
> values are recorded in each item's `forbid` list.

Issue C. Ridgeline Systems AB, Gävle. Normative interface specification for
Ridgeline R-7 vehicles and the wayside.

## 1. Coupler classes

| Coupler | Drawbar force (kN) | Service weight (t) | Coupler face width (mm) |
| --- | --- | --- | --- |
| RL-A1 | 1,180 | 86 | 105 |
| RL-B2 | 2,450 | 140 | 135 |
| RL-C3 | 3,910 | 186 | 165 |
| RL-D4 | 5,220 | 240 | 195 |

Class RL-A1 is the reference class for all other parameters unless a table says
otherwise. A vehicle of service weight W is in class RL-A1 below 100 t, RL-B2
from 100 t to 155 t, RL-C3 above 155 t to 210 t, and RL-D4 above 210 t.

## 2. Axle load classes

| Axle load class | Maximum line speed (km/h) | Track gauge (mm) |
| --- | --- | --- |
| 22.5 t | 120 | 1435 |
| 25.0 t | 160 | 1435 |
| 27.5 t | 200 | 1668 |
| 30.0 t | 240 | 1668 |

Track gauge is standard gauge where the table says 1435 mm. 1668 mm is the
Ridgeline broad gauge, used on the northern lines only.

## 3. Traction supply

| System | Supply | Frequency | Max current (A) |
| --- | --- | --- | --- |
| RL-DC 1.5kV | 1,500 V DC | — | 4,200 |
| RL-AC 25kV | 25,000 V AC | 50 Hz | 1,150 |
| RL-AC 15kV | 15,000 V AC | 60 Hz | 1,480 |
| RL-BAT 900 | 900 V DC battery | — | 2,600 |

The RL-BAT 900 supply is fitted only to R-7 units built for the
Kirkwall-Braemar route, which has no electrification.

## 4. Brake performance

Deceleration from 200 km/h in service brake application is not less than
0.95 m/s². Emergency deceleration is not less than 1.40 m/s². The maximum
brake cylinder pressure is 380 kPa and the wheel-slide protection threshold is
set at 12% wheel slip.

Brake pipe charging time from empty to full is not more than 45 seconds on the
RL-B2 class and not more than 60 seconds on the RL-C3 class.

## 5. Doors and body

| Door type | Clear width (mm) | Position per side |
| --- | --- | --- |
| Single-leaf | 1,300 | 4 |
| Double-leaf | 2,600 | 2 |
| Plug | 1,600 | 3 |

A vehicle with plug doors shall not be operated above 200 km/h with a door
open. Clear width is measured with the door fully open and the threshold at
nominal ride height.

## 6. Environmental and fault codes

Vehicles shall operate between -45 °C and +55 °C ambient. Ingress protection
is IP66 for traction equipment and IP54 for body equipment.

| Code | Meaning | Response |
| --- | --- | --- |
| F-101 | Door interlock bypassed | Stop at next station |
| F-118 | Brake cylinder overpressure | Reduce to 60 km/h |
| F-142 | Traction supply outside tolerance | Hold and request clearance |
| F-207 | Wheel-slide protection active | No response; log and continue |
| F-233 | Door drive timeout | Remove from service |
| F-301 | Wayside link loss | Continue in degraded mode |

## 7. Commissioning

A vehicle is commissioned after a static test of 30 minutes at nominal supply,
a brake test at not less than 12% of service weight, and a run at not less
than 30 km/h on the test track. The test track length for commissioning is
2,400 m, which is sufficient for a 240 km/h run under the braking figures in
section 4.