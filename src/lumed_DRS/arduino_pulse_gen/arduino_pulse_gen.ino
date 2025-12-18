int TTL_PIN = 8;
int receiver_TTL_PIN = 7;
#define potentiometer_pin A0
unsigned long previousSampleTime = 0;
const long sampleInterval = 1; // Sample every 500 milliseconds
unsigned long pulse_start_time = 0; // ms initialize the pulse start time variable
unsigned long delay_time  = 0;// ms add a time delay between the user input to start pulse and the actual pulse
unsigned long receive_time  = 0; // initialize the message reception time variable
int pulseDuration = 100; // Pulse duration remains 100ms 
int pulseON = 0;
int pinState = 0;
int receiverPinState = 0;
String msg = "OFF"; // Default pulse value to "OFF"
String received_msg = ""; // Received message initialisation
int c = 0;
void setup() {
  Serial.begin(9600); //baud rate
  pinMode(TTL_PIN, OUTPUT);
  pinMode(receiver_TTL_PIN, INPUT);
  Serial.setTimeout(100); // ms Timeout of the Serial.readString() function
}

void loop(){
  // Verify a serial connection has been established
  unsigned long currentMillis = millis();
  //if (Serial.available()==0){
  
  //Serial.println("Serial.available():" + String(Serial.available()));

  // //Set the message to a received message if it is not None
  // if (received_msg.length()>0){

  //Sampling the TTL_PIN to plot it
  if (currentMillis - previousSampleTime >= sampleInterval) {
    previousSampleTime = currentMillis;
    // Read the current state of the pin and send it to the plotter
    pinState = digitalRead(TTL_PIN);
    //receiverPinState = digitalRead(receiver_TTL_PIN); 
    //Serial.println("i am in the printing logic"); 
    //Serial.println("-----iteration: "+ String(c));
    //Serial.println("TTL_PIN state: "+ String(pinState)); 
    //Serial.println(pinState);
    //Serial.println(msg); //"current message:" + msg
    //Serial.println(msg);
  }

  //Checks if there are bytes (characters) available for reading if that is the case the message is set to the received message 
  if (Serial.available()>0){
    receive_time = currentMillis;
    received_msg = Serial.readStringUntil('\n'); //waits 100 ms for user input
    //Serial.println("received message: " + received_msg);
    //Serial.println("received time: " + String(receive_time));
    received_msg.trim();
    if (received_msg == "*idn?"){
      Serial.println("DRS_arduino");
      return;
    }
    else{
      msg = received_msg;
    }  
  }

  // }
  // When arduino receives a "ON" message, it sends a pulse with duration 'pulseDuration'
  if (msg == "ON"){
    unsigned long since_time = currentMillis - receive_time;
    //Serial.println("time since received message: " + since_time);
    if ((pulseON == 0) && (currentMillis - receive_time >= delay_time)){// && (currentMillis - receive_time >= delay_time)
      pulse_start_time = currentMillis;
      //Serial.println("Started pulse generation");
      digitalWrite(TTL_PIN, HIGH);
      //Serial.println("in pulse on");
      pulseON = 1;
    }
    else if((pulseON == 1) && (currentMillis - pulse_start_time >= pulseDuration)) {
      digitalWrite(TTL_PIN, LOW); // Turn off the pulse
      msg = "OFF"; // set the message to low so that next iterations have a low signal
      // Serial.println("currentMillis - pulse_start_time: " + String(currentMillis - pulse_start_time));
      // Serial.println("pulseDuration: " + String(pulseDuration));
      // Serial.println("in pulse off after time ran out");
      pulseON = 0;
    }
  }
  else if (msg == "OFF"){
    digitalWrite(TTL_PIN, LOW);
    //Serial.println("in pulse off after forced off");
    pulseON = 0;
  }

 

}
