##
## Import necessary to provide timing in the main loop
##
from time import sleep
from datetime import datetime

##
## Imports required to allow us to build a fully functional state machine
##
from statemachine import StateMachine, State

##
## Imports necessary to provide connectivity to the 
## thermostat sensor and the I2C bus
##
import board
import adafruit_htu21d

##
## These are the packages that we need to pull in so that we can work
## with the GPIO interface on the Raspberry Pi board and work with
## the 16x2 LCD display
import digitalio
import adafruit_character_lcd.character_lcd as characterlcd

## This imports the Python serial package to handle communications over the
## Raspberry Pi's serial port. 
import serial

##
## Imports required to handle our Button, and our PWMLED devices
##
from gpiozero import Button, PWMLED

##
## This package is necessary so that we can delegate the blinking
## lights to their own thread so that more work can be done at the
## same time
##
from threading import Thread

##
## This is needed to get coherent matching of temperatures.
##
from math import floor

##
## Adds the PID controller for smarter and smoother responses to temp fluctuations
##
from simple_pid import PID

##
## Adds mongo to be able to send info to mongoDB
##
from pymongo import MongoClient


##
## DEBUG flag - boolean value to indicate whether or not to print 
## status messages on the console of the program
## 
DEBUG = True

##
## Create an I2C instance so that we can communicate with
## devices on the I2C bus.
##
i2c = board.I2C()

##
## Initialize our Temperature and Humidity sensor
##
thSensor = adafruit_htu21d.HTU21D(i2c)

##
## Initialize our serial connection
##
## Because we imported the entire package instead of just importing Serial and
## some of the other flags from the serial package, we need to reference those
## objects with dot notation.
##
## e.g. ser = serial.Serial
##
ser = serial.Serial(
        port='/dev/ttyS0', # This would be /dev/ttyAM0 prior to Raspberry Pi 3
        baudrate = 115200, # This sets the speed of the serial interface in
                           # bits/second
        parity=serial.PARITY_NONE,      # Disable parity
        stopbits=serial.STOPBITS_ONE,   # Serial protocol will use one stop bit
        bytesize=serial.EIGHTBITS,      # We are using 8-bit bytes 
        timeout=1          # Configure a 1-second timeout
)

## Focuses on making the LED more automated 
## Deleted the ifs for just storing the Led Objects
class TemperatureIndicator:
       def __init__(self, red_pin=18, blue_pin=23):
           self.red = PWMLED(red_pin)
           self.blue = PWMLED(blue_pin)

       def clear(self):
           self.red.off()
           self.blue.off()

##
## ManagedDisplay - Class intended to manage the 16x2 
## Display
class ManagedDisplay():
    ## Class Initialization method to setup the display
    def __init__(self):
        ##
        ## Setup the six GPIO lines to communicate with the display.
        ## This leverages the digitalio class to handle digital 
        ## outputs on the GPIO lines. There is also an analagous
        ## class for analog IO.
        self.lcd_rs = digitalio.DigitalInOut(board.D17)
        self.lcd_en = digitalio.DigitalInOut(board.D27)
        self.lcd_d4 = digitalio.DigitalInOut(board.D5)
        self.lcd_d5 = digitalio.DigitalInOut(board.D6)
        self.lcd_d6 = digitalio.DigitalInOut(board.D13)
        self.lcd_d7 = digitalio.DigitalInOut(board.D26)

        # Modify this if you have a different sized character LCD
        self.lcd_columns = 16
        self.lcd_rows = 2 

        # Initialise the lcd class
        self.lcd = characterlcd.Character_LCD_Mono(self.lcd_rs, self.lcd_en, 
                    self.lcd_d4, self.lcd_d5, self.lcd_d6, self.lcd_d7, 
                    self.lcd_columns, self.lcd_rows)

        # wipe LCD screen before we start
        self.lcd.clear()

    ##
    ## cleanupDisplay - Method used to cleanup the digitalIO lines that
    ## are used to run the display.
    ##
    def cleanupDisplay(self):
        # Clear the LCD first - otherwise we won't be abe to update it.
        self.lcd.clear()
        self.lcd_rs.deinit()
        self.lcd_en.deinit()
        self.lcd_d4.deinit()
        self.lcd_d5.deinit()
        self.lcd_d6.deinit()
        self.lcd_d7.deinit()
        
    ##
    ## clear - Convenience method used to clear the display
    ##
    def clear(self):
        self.lcd.clear()

    ##
    ## updateScreen - Convenience method used to update the message.
    ##
    def updateScreen(self, message):
        self.lcd.clear()
        self.lcd.message = message

    ## End class ManagedDisplay definition  

##
## Initialize our display
##
screen = ManagedDisplay()

##
## TemperatureMachine - This is our StateMachine implementation class.
## The purpose of this state machine is to manage the three states
## handled by our thermostat:
##
##  off
##  heat
##  cool
##
##
class TemperatureMachine:
    "A state machine designed to manage our thermostat"

    ##
    ## Default temperature setPoint is 72 degrees Fahrenheit
    ##
    setPoint = 72

    def __init__(self):
        self.setPoint = 72
        self.indicator = TemperatureIndicator()

        # PID controller setup: target = setPoint
        self.pid = PID(Kp=1.2, Ki=0.01, Kd=0.05, setpoint=self.setPoint)
        self.pid.output_limits = (0,1) # LED brightness range

        self.client = MongoClient(##currently empty to keep info safe)
        self.db = self.client['thermostat_data']
        self.collection = self.db['temperature_logs']
    
    def processTempIncButton(self):
        if(DEBUG):
            print("Increasing Set Point")

        self.setPoint += 1
        self.pid.setpoint = self.setPoint # Keeps PID aligned
        self.updateLights()

    ##
    ## processTempDecButton - Utility method used to update the 
    ## setPoint for the temperature. This will decrease the setPoint
    ## by a single degree. This is triggered by the button_pressed event
    ## handler for our third button
    ##
    def processTempDecButton(self):
        if(DEBUG):
            print("Decreasing Set Point")

        self.setPoint -= 1
        self.pid.setpoint = self.setPoint # Keeps PID aligned
        self.updateLights()

    ##
    ## updateLights - Utility method to update the LED indicators on the 
    ## Thermostat
    ##
    def updateLights(self):
        temp = self.getFahrenheit()
        output = self.pid(temp)

        hysteresis = 0.5
        diff = abs(temp - self.setPoint)

        if DEBUG:
            print(f"[PID] Temp: {temp}, SetPoint: {self.setPoint}, Output: {output}")

        # Use PID output to dim red or blue depending on temp
        if temp < self.setPoint:
            self.indicator.red.value = output
            self.indicator.blue.value = 0
        elif temp > self.setPoint:
            self.indicator.blue.value = output
            self.indicator.red.value = 0
        else:
            self.indicator.red.value = 0.2
            self.indicator.blue.value = 0.2

    ##
    ## run - kickoff the display management functionality of the thermostat
    ##
    def run(self):
        myThread = Thread(target=self.manageMyDisplay)
        myThread.start()

    ##
    ## Get the temperature in Fahrenheit
    ##
    def getFahrenheit(self):
        t = thSensor.temperature
        return (((9/5) * t) + 32)
    
    ##
    ## Configure output string for the Thermostat Server
    ## Added timestamp to code to keep track of time for database
    ##
    def setupSerialOutput(self):
        # Add timestamp for database logging
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        output = (
            f'{{'
            f'"timestamp": "{timestamp}", '
            f'"temp": {round(self.getFahrenheit(), 1)}, '
            f'"setPoint": {self.setPoint}'
            f'}}'
        )
        return output
    
    ## Continue display output
    endDisplay = False

    ##
    ##  This function is designed to manage the LCD Display
    ##
    def manageMyDisplay(self):
        counter = 1
        altCounter = 1
        while not self.endDisplay:
            ## Only display if the DEBUG flag is set
            if(DEBUG):
                print("Processing Display Info...")
    
            ## Grab the current time        
            current_time = datetime.now()
    
            ## Setup display line 1

            lcd_line_1 = current_time.strftime( "%m/%d %H:%M:%S") + "\n"
    
            ## Setup Display Line 2
            if(altCounter < 6):
                lcd_line_2 = f"Temp: {round(self.getFahrenheit(), 1)}"    
                altCounter += 1
            else:
                lcd_line_2 = f"Set Point: {self.setPoint}F"    
                altCounter = altCounter + 1
                if(altCounter >= 11):
                    # Run the routine to update the lights every 10 seconds
                    # to keep operations smooth
                    self.updateLights()
                    altCounter = 1
    
            ## Update Display
            screen.updateScreen(lcd_line_1 + lcd_line_2)
    
            ## Update server every 30 seconds & log to MongoDB every 5 minutes
            if DEBUG:
                print(f"Counter: {counter}")

            # Every 30 seconds → send serial data
            if (counter % 30) == 0:
                ser.write((self.setupSerialOutput() + "\n").encode())

            # Every 5 minutes → log to MongoDB
            if (counter % 300) == 0:
                self.logToDatabase()

            counter += 1
            sleep(1)

        ## Cleanup display
        screen.cleanupDisplay()


    def logToDatabase(self):
        log_entry = {
            "timestamp": datetime.now(),
            "temperature": round(self.getFahrenheit(), 1),
            "setPoint": self.setPoint
        }
        self.collection.insert_one(log_entry)
        if DEBUG:

            print("Logged to MongoDB:", log_entry)
    ## End class TemperatureMachine definition


##
## Setup our State Machine
##
tsm = TemperatureMachine()
tsm.run()

## Configure our Red button to use GPIO 25 and to execute
## the function to increase the setpoint by a degree.
##
redButton = Button(25)

redButton.when_pressed = tsm.processTempIncButton

##
## Configure our Blue button to use GPIO 12 and to execute
## the function to decrease the setpoint by a degree.
##
blueButton = Button(12)

blueButton.when_pressed = tsm.processTempDecButton

##
## Setup loop variable
##
repeat = True

##
## Repeat until the user creates a keyboard interrupt (CTRL-C)
##
while repeat:
    try:
        ## wait
        sleep(30)

    except KeyboardInterrupt:
        ## Catch the keyboard interrupt (CTRL-C) and exit cleanly
        ## we do not need to manually clean up the GPIO pins, the 
        ## gpiozero library handles that process.
        print("Cleaning up. Exiting...")

        ## Stop the loop
        repeat = False
        
        ## Close down the display
        tsm.endDisplay = True
        tsm.indicator.clear()
        sleep(1)
