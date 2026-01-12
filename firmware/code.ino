/**
 * ---------------------------------------------------------------------------------
 * SYSTÈME DE CONTRÔLE D'ACCÈS BIOMÉTRIQUE - CODE ESP32 (MODE USB UNIQUEMENT)
 * ---------------------------------------------------------------------------------
 * Ce code gère un capteur d'empreintes digitales (JM-101B) et communique 
 * EXCLUSIVEMENT via le câble USB avec la passerelle Python (bridge.py).
 * 
 * FONCTIONNALITÉS :
 * 1. Mode Scan (Défaut) : Vérifie l'accès et envoie l'ID reconnu au PC.
 * 2. Mode Inscription : Piloté par le site web via le câble USB.
 * 3. Mode Suppression : Effacement piloté via USB.
 * 4. Mode Synchronisation : Envoi de l'état de la mémoire via USB.
 * ---------------------------------------------------------------------------------
 */

#include <Arduino.h>
#include <Adafruit_Fingerprint.h>

// --- BROCHES (PINS) ---
#define PIN_LED_VERTE 25  // Indicateur : Accès accordé
#define PIN_LED_ROUGE 26  // Indicateur : Accès refusé / Erreur
#define PIN_RX 16         // Liaison Série vers le capteur (RX)
#define PIN_TX 17         // Liaison Série vers le capteur (TX)

// --- INITIALISATION ---
HardwareSerial serialCapteur(2); // Port série matériel 2 pour le capteur
Adafruit_Fingerprint capteur = Adafruit_Fingerprint(&serialCapteur);

// --- PROTOTYPES DES FONCTIONS ---
void processCommand(String payload);
void verifyFinger();
void enregistrerEmpreinte(int id);
void syncUsers();
void sendActiveUsers(String ids);
void sendAccessToPC(int id, int confidence);

// =================================================================================
// SETUP : Initialisation au démarrage
// =================================================================================
void setup() {
  // Communication avec le PC via USB
  Serial.begin(115200); 
  delay(500);

  pinMode(PIN_LED_VERTE, OUTPUT);
  pinMode(PIN_LED_ROUGE, OUTPUT);

  // Initialisation du capteur biométrique
  serialCapteur.begin(57600, SERIAL_8N1, PIN_RX, PIN_TX);
  
  Serial.println("\n🔍 Système Biométrique USB Démarré...");
  
  if (capteur.verifyPassword()) {
    Serial.println("✅ Capteur opérationnel.");
  } else {
    Serial.println("❌ Erreur Capteur. Vérifiez le câblage.");
    while (1) { delay(1); }
  }
}

// =================================================================================
// LOOP : Boucle principale
// =================================================================================
void loop() {
  // 1. ÉCOUTE DES COMMANDES PC (Bridge.py -> USB)
  // On vérifie si une instruction arrive du site web
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() > 0) {
      processCommand(cmd); // Exécuter la commande (Enroll, Delete, etc.)
    }
  }

  // 2. MODE SCAN PAR DÉFAUT
  // On ne scanne que si aucune commande USB n'attend d'être lue
  if (Serial.available() == 0) {
    verifyFinger();
  }
  
  delay(50); // Stabilité
}

// =================================================================================
// LOGIQUE DE COMMANDE (PILOTAGE PAR LE PC)
// =================================================================================

/**
 * Traite les ordres envoyés par le script bridge.py
 */
void processCommand(String payload) {
  if (payload.startsWith("ENROLL:")) {
    int id = payload.substring(7).toInt();
    if (id > 0) {
      Serial.println("\n[PC] -> Ordre d'inscription ID #" + String(id));
      enregistrerEmpreinte(id);
    }
  }
  else if (payload.startsWith("DELETE:")) {
    int id = payload.substring(7).toInt();
    if (id > 0) {
      if (capteur.deleteModel(id) == FINGERPRINT_OK) {
        Serial.printf("✅ [PC] ID #%d supprimé de la mémoire.\n", id);
      }
    }
  }
  else if (payload.startsWith("SYNC_USERS")) {
    Serial.println("\n[PC] -> Synchronisation demandée...");
    syncUsers();
  }
}

// =================================================================================
// FONCTIONNALITÉS BIOMÉTRIQUES
// =================================================================================

void verifyFinger() {
  uint8_t p = capteur.getImage();
  if (p != FINGERPRINT_OK) return;

  p = capteur.image2Tz();
  if (p != FINGERPRINT_OK) return;

  p = capteur.fingerSearch();
  if (p == FINGERPRINT_OK) {
    Serial.println("\n🔓 ACCÈS RECONNU");
    digitalWrite(PIN_LED_VERTE, HIGH);
    
    // Envoi des données au PC via le protocole bridge.py
    sendAccessToPC(capteur.fingerID, capteur.confidence);
    
    delay(2000); // Temps d'ouverture
    digitalWrite(PIN_LED_VERTE, LOW);
  } else {
    Serial.println("\n🔒 INCONNU");
    digitalWrite(PIN_LED_ROUGE, HIGH);
    delay(1000);
    digitalWrite(PIN_LED_ROUGE, LOW);
  }
}

void enregistrerEmpreinte(int id) {
  int p = -1;
  Serial.println("Action : Posez le doigt pour Capture 1...");
  
  // LED Verte clignote pour indiquer le mode inscription
  for(int i=0; i<3; i++) { digitalWrite(PIN_LED_VERTE, HIGH); delay(100); digitalWrite(PIN_LED_VERTE, LOW); delay(100); }

  while (p != FINGERPRINT_OK) { p = capteur.getImage(); }
  capteur.image2Tz(1);
  Serial.println("Action : Retirez le doigt...");
  delay(2000);
  while (p != FINGERPRINT_NOFINGER) { p = capteur.getImage(); }

  Serial.println("Action : Posez à nouveau pour Capture 2...");
  p = -1;
  while (p != FINGERPRINT_OK) { p = capteur.getImage(); }
  capteur.image2Tz(2);

  if (capteur.createModel() == FINGERPRINT_OK) {
    if (capteur.storeModel(id) == FINGERPRINT_OK) {
      Serial.println("✅ SUCCÈS : ID #" + String(id) + " enregistré.");
      digitalWrite(PIN_LED_VERTE, HIGH); delay(2000); digitalWrite(PIN_LED_VERTE, LOW);
    }
  } else {
    Serial.println("❌ ÉCHEC : Incohérence des empreintes.");
    digitalWrite(PIN_LED_ROUGE, HIGH); delay(2000); digitalWrite(PIN_LED_ROUGE, LOW);
  }
}

// =================================================================================
// COMMUNICATION PC (VIA USB)
// =================================================================================

void sendAccessToPC(int id, int confidence) {
  // Envoi formatté pour le script bridge.py
  Serial.printf("__ACCESS__:{\"fingerID\":%d, \"confidence\":%d}\n", id, confidence);
}

void syncUsers() {
  String foundIds = "";
  int count = 0;
  for (int id = 1; id <= 50; id++) {
    if (capteur.loadModel(id) == FINGERPRINT_OK) {
       if (count > 0) foundIds += ",";
       foundIds += String(id);
       count++;
    }
  }
  Serial.printf("✅ Synchro : %d IDs trouvés.\n", count);
  sendActiveUsers(foundIds);
}

void sendActiveUsers(String ids) {
  // Envoi de la liste au bridge
  Serial.printf("__USERS__:{\"ids\":[%s]}\n", ids.c_str());
}