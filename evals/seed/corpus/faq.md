# Aurora Widget Support FAQ

## The status LED is solid red

A solid red LED means the widget has logged a fault code. Check the fault
code table in the specification sheet: E-41 is blade motor overcurrent,
E-42 is battery temperature, E-43 is a failed firmware update.

## The widget will not pair

Hold the pair button for 3 seconds until the LED blinks blue, then pair
from the app. A maximum of 3 devices can be paired per widget under
firmware 3.2.1; earlier firmware allowed only 2.

## Battery life seems short

Expected battery life is 12 hours on the standard AW-2000-X under typical
use with the eco profile enabled in the app. Heavy blade use reduces this
to roughly 7 hours.

## Updating firmware

Firmware updates are delivered over the air through the Aurora app.
Version 3.2.1 fixes an issue where E-43 could be logged spuriously.
