import serial
import requests
import json
import time

# --- CONFIGURATION ---
# Port série (à vérifier dans Arduino IDE, ex: /dev/cu.usbserial-0001)
SERIAL_PORT = '/dev/cu.usbserial-0001' 
BAUD_RATE = 115200
# URL de votre serveur Flask local
SERVER_URL = 'http://localhost:5000/access'

def start_bridge():
    print(f"🚀 Démarrage de la passerelle USB -> Flask...")
    print(f"📡 Écoute sur {SERIAL_PORT} à {BAUD_RATE} baud...")
    
    try:
        # Initialisation de la connexion série
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)  # Attendre le reset de l'ESP32
        
        while True:
            if ser.in_waiting > 0:
                # Lire une ligne depuis l'ESP32
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                
                # Détecter notre préfixe spécial
                if line.startswith("__ACCESS__:"):
                    print(f"\n📥 Donnée reçue de l'ESP32 : {line}")
                    
                    try:
                        # Extraire le JSON
                        json_str = line.split("__ACCESS__:", 1)[1]
                        data = json.loads(json_str)
                        
                        # Envoyer au serveur Flask
                        print(f"📤 Envoi au serveur Flask ({SERVER_URL})...")
                        response = requests.post(SERVER_URL, json=data)
                        
                        if response.status_code == 201:
                            print("✅ Succès ! Donnée enregistrée en base.")
                        else:
                            print(f"❌ Erreur serveur : {response.status_code}")
                            
                    except Exception as e:
                        print(f"⚠️ Erreur de parsing/envoi : {e}")
                
                elif line.startswith("__USERS__:"):
                    print(f"\n📥 Liste d'utilisateurs reçue : {line}")
                    try:
                        json_str = line.split("__USERS__:", 1)[1]
                        data = json.loads(json_str)
                        requests.post('http://localhost:5000/api/active_users', json=data)
                        print("✅ Liste synchronisée avec le serveur.")
                    except Exception as e:
                        print(f"⚠️ Erreur de synchronisation : {e}")

                elif line:
                    # Afficher les autres logs pour le debug
                    print(f"LOG: {line}")
            
            # --- PARTIE ÉMISSION (PC -> ESP32) ---
            try:
                # Vérification toutes les 1 seconde de façon stable
                time.sleep(0.1) 
                
                # On ne vérifie l'API que si le port est libre
                resp = requests.get('http://localhost:5000/api/command', timeout=0.5)
                if resp.status_code == 200:
                    cmd = resp.text.strip()
                    
                    if cmd not in ["WAIT:0", "wait:0"]:
                        # Envoi Série
                        print(f"📤 Envoi Commande à l'ESP32 : {cmd}")
                        ser.write((cmd + '\n').encode('utf-8'))
                        ser.flush() # S'assurer que c'est bien parti
                        
                        # Reset immédiat de la commande sur le serveur
                        requests.post('http://localhost:5000/api/command', json={"action": "wait", "id": 0})
                            
            except Exception as e:
                pass 

    except serial.SerialException as e:
        print(f"❌ Erreur Port Série : {e}")
        print("Vérifiez que l'ESP32 est branché et que l'Arduino IDE ne bloque pas le port (fermez le Serial Monitor).")
    except KeyboardInterrupt:
        print("\n👋 Arrêt de la passerelle.")

if __name__ == "__main__":
    start_bridge()
