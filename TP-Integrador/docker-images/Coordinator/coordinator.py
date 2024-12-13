from datetime import datetime, timezone
import os
import threading
from flask import Flask, request, jsonify
import pika
import json
import time
import redis
import sys
import hashlib
import random
from redis_utils import RedisUtils

app = Flask(__name__)
prefix = "000"
last_task = None
last_id = 0
redis_blocked = False

time_challenge_initiate: datetime = datetime.now(timezone.utc)
time_challenge_terminated: datetime = datetime.now(timezone.utc)


def calcular_hash(data):
    hash = hashlib.md5()
    hash.update(data.encode('utf-8'))
    return hash.hexdigest()

@app.route('/transaction', methods=['POST'])
def transaction():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se proporcionaron datos.'}), 400
        
        required_fields = ['user_from', 'user_to', 'amount']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Faltan uno o más campos necesarios.'}), 400

        print(f"Transacción recibida: {data}")

        # Encolar la transacción en RabbitMQ!
        channel.basic_publish(exchange='', routing_key='transactions', body=json.dumps(data))
        return jsonify({'message': 'Transacción recibida y encolada en RabbitMQ.', "data": data}), 200
    except Exception as e:
        return jsonify(e)

@app.route('/status', methods=['GET'])
def status():
    global redis_client, connection 
    try:
        # Verificar conexión a Redis
        redis_client.ping()  # Si la conexión está bien, no lanzará excepciones
        # Verificar conexión a RabbitMQ
        if connection.is_open:  # Si la conexión está abierta, no lanzará excepciones
            return jsonify({'message': 'running'}), 200
        else:
            return jsonify({'error': 'No se está conectado a RabbitMQ'}), 500
    except redis.ConnectionError:
        return jsonify({'error': 'No se está conectado a Redis'}), 500
    except pika.exceptions.AMQPConnectionError:
        return jsonify({'error': 'No se está conectado a RabbitMQ'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def postear_task(last_element):
    global last_id
    global last_task
    global time_challenge_initiate

    transactions = []
    while True:
        method_frame, header_frame, body = channel.basic_get(queue='transactions', auto_ack=False)
        if method_frame:
            # Agregar la transacción al array de transacciones
            transactions.append(json.loads(body))
            # ACK del mensaje recibido
            channel.basic_ack(delivery_tag=method_frame.delivery_tag)
        else:
            break  # No hay más mensajes para recibir
        
    if transactions:
        task = {
            "id": last_id,
            "transactions": transactions, 
            "prefix": prefix,
            "num_min": 0,
            "num_max": 99999999,
            "last_hash": last_element["hash"] if last_element else ""
        }
        # Guardo en Redis la tarea:
        redis_utils.post_task(last_id, task)   
        last_task = task
        
        # Encolar en RabbitMQ en el topic
        print("PUBLICANDO TAREA!!!!!")
        channel.basic_publish(exchange='blockchain_challenge', routing_key='tasks', body=json.dumps(task))
        print(f"Encolando tarea para los workers. Descripcion de la tarea: {task}")
        print()
        
        # Inicio el timer
        time_challenge_initiate = datetime.now(timezone.utc)
    else:
        print(f"No hay transacciones por el momento.")
        print()

def repostear_task():
    global last_task
    global time_challenge_initiate

    # Guardo en Redis la tarea:
    redis_utils.post_task(last_id, last_task)   
    
    # Encolar en RabbitMQ en el topic
    channel.basic_publish(exchange='blockchain_challenge', routing_key='tasks', body=json.dumps(last_task))
    print(f"Encolando tarea para los workers. Descripcion de la tarea: {last_task}")
    print()
    
    # Inicio el timer
    time_challenge_initiate = datetime.now(timezone.utc)

def task_building():
    global prefix
    global time_challenge_initiate
    global redis_utils
    global last_task
    global last_id

    while True:
        print("Comprobando si hay transacciones para generar task...")
        print()

        last_element = redis_utils.get_latest_element() # Obtener último bloque de la blockchain
        # Aumento el last_id con respecto al ultimo bloque de la blockchain
        last_id = last_element["id"] + 1 if last_element else 0 

        # Si la ultima tarea que se publicó es igual al ultimo id, significa que ningun worker ha publicado la solución
        if last_task != None and last_task['id'] == last_id:
            print("ENTRÉ EN EL IF!!!!")
            # Obtengo la diferencia de tiempo
            time_challenge_terminated = datetime.now(timezone.utc)
            time_difference = (time_challenge_terminated - time_challenge_initiate).total_seconds()

            # Si pasaron 5 minutos y todavía nadie respondio, se disminuye el prefijo
            if time_difference >= 300 and len(prefix) > 1:
                prefix = prefix[:-1]  # Quitar un "0"
                print(f"Ningún worker resolvió la tarea en 5 minutos, disminuyendo dificultad: {prefix}")
                print()
                last_task["prefix"] = prefix
                # Se repostea la misma tarea que nadie pudo responder, pero con un prefijo menos
                repostear_task()
            
            time.sleep(30)
            continue # Vuelvo a ejecutar el bucle, sin pasar por postear_task
        
        print("Voy a postear una tarea!")
        postear_task(last_element)                
        time.sleep(30)  # Cambiar a 60

@app.route("/solved_task", methods=["POST"])
def solved_task():
    global prefix
    global time_challenge_initiate
    global time_challenge_terminated
    global redis_utils
    global redis_blocked
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se proporcionaron datos.'}), 400
        
        print(f"Un Worker envió su solución:\n{data}")
        print()

        required_fields = ['id', 'number', 'transactions', 'hash']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Faltan uno o más campos necesarios.'}), 400

        block_id = data.get("id")
        number = data.get("number") # nonce
        transactions = data.get("transactions")
        received_hash = data.get("hash")

        if redis_utils.exists_id(block_id):
            return jsonify({'error': 'El bloque ya existe.'}), 400

        # Comparo el prefijo
        prefijo = redis_utils.get_task(block_id)["prefix"]
        if not received_hash.startswith(prefijo):
            return jsonify({'error': 'El hash no tiene el prefijo requerido.'}), 400

        if redis_utils.exists_id(block_id):
            return jsonify({'error': 'El bloque ya existe.'}), 400
        
        last_element = redis_utils.get_latest_element()
        if last_element:
            current_hash = last_element['hash']
        else:
            current_hash = ""
        
        combined_data = f"{number}{len(transactions)}{current_hash}"
        hash_calculado = calcular_hash(combined_data)

        print(f"Hash recibido: {received_hash}")
        print(f"Hash calculado localmente: {hash_calculado}")
        print()

        if received_hash != hash_calculado:
            return jsonify({'error': 'Hash invalido. Descartado.'}), 400
        
        if redis_utils.exists_id(block_id):
            return jsonify({'error': 'El bloque ya existe.'}), 400

        block = {
            "id": block_id,
            "hash": received_hash,
            "transactions": transactions,
            "prefix": prefijo,
            "number": number,   # nonce
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_hash": current_hash
        }

        # Guardo el bloque en Redis
        if redis_utils.exists_id(block_id):
            return jsonify({'error': 'El bloque ya existe.'}), 400
        
        redis_utils.post_message(message=block)

        # Calculo el prefijo para el próximo bloque
        time_challenge_terminated = datetime.now(timezone.utc)
        time_difference = (time_challenge_terminated - time_challenge_initiate).total_seconds()

        if time_difference > 75 and len(prefix) > 1:
            prefix = prefix[:-1]  # Quitar un "0"
            print(f"NUEVO PREFIJO (disminuyo): {prefix}")
            print()
        elif time_difference < 30:
            prefix += "0"
            print(f"NUEVO PREFIJO (aumento): {prefix}")
            print()

        redis_utils.delete_task(block_id)

        return jsonify({"message": "Bloque añadido a la Blockchain."}), 200
    except Exception as e:
        return jsonify({"error": e}), 500

if __name__ == "__main__":
    # Configuración de Redis
    redis_host = os.environ.get("REDIS_HOST")
    redis_port = os.environ.get("REDIS_PORT")
    redis_db = os.environ.get("REDIS_DB")
    # Configuración de RabbitMQ
    rabbitmq_host = os.environ.get("RABBITMQ_HOST")
    rabbitmq_port = os.environ.get("RABBITMQ_PORT")
    rabbitmq_user = os.environ.get("RABBITMQ_USER")
    rabbitmq_password = os.environ.get("RABBITMQ_PASSWORD")
    rabbitmq_queue = 'transactions'
    rabbitmq_exchange = 'blockchain_challenge'
    connected_redis = False
    while not connected_redis:
        try:
            connected_redis = False
            redis_client = redis.StrictRedis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)
            redis_utils = RedisUtils(redis_client)
            connected_redis = True
            print("Conectado a Redis")
            print()
        except Exception as e:
            print(f"No se pudo conectar a Redis: {e}")
            print("Reintentando en 3 segundos...")
            time.sleep(3)
    connected_rabbit = False
    while not connected_rabbit:
        try:
            credentials = pika.PlainCredentials(rabbitmq_user, rabbitmq_password)
            parameters = pika.ConnectionParameters(host=rabbitmq_host, port=rabbitmq_port, credentials=credentials, heartbeat=0)
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            # Crear cola
            channel.queue_declare(queue=rabbitmq_queue, durable=True)
            # Crear exchange tipo topic
            channel.exchange_declare(exchange=rabbitmq_exchange, exchange_type='topic', durable=True)
            connected_rabbit = True
            print("Conectado a RabbitMQ!")
            print()
        except Exception as e:
            print(f"Error al conectar con RabbitMQ: {e}")
            print("Reintentando en 3 segundos...")
            time.sleep(3)

    threading.Thread(target=task_building).start()
    app.run(host="0.0.0.0", port=5000)