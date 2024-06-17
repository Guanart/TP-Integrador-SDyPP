from datetime import datetime, timezone
import threading
from flask import Flask, request, jsonify
import pika
import json
import time
import redis
import sys
import hashlib
from redis_utils import RedisUtils

redis_utils = RedisUtils()

app = Flask(__name__)
prefix = "000"
prefix_lock = threading.Lock()

time_challenge_initiate: datetime = datetime.now(timezone.utc)
time_challenge_initiate_lock = threading.Lock()
time_challenge_terminated: datetime = datetime.now(timezone.utc)


def calcular_hash(data):
    hash = hashlib.md5()
    hash.update(data.encode('utf-8'))
    return hash.hexdigest()

@app.route('/')
def index():
    return f"Coordinador funcionando!"

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
        # Encolar en RabbitMQ!
        channel.basic_publish(exchange='', routing_key='transactions', body=json.dumps(data))
        return jsonify({'message': 'Transacción recibida y encolada en RabbitMQ.', "data": data}), 200
    except Exception as e:
        return jsonify(e)

@app.route('/status', methods=['GET'])
def status():
    return jsonify({'message': 'running'}), 200

def task_building():
    global prefix
    global time_challenge_initiate
    global redis_utils
    
    while True:
        print("Buscando nuevas transacciones para generar task...")
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
            with prefix_lock:
                current_prefix = prefix  # Leer el valor de prefix protegido por el lock

            
            print(f"""
---------------------------------------------------------------------
---------------------------------------------------------------------
---------------------------------------------------------------------
PREFIJO: {current_prefix}
---------------------------------------------------------------------
---------------------------------------------------------------------
---------------------------------------------------------------------
""")

            last_element = redis_utils.get_latest_element() # Obtener último bloque de la blockchain
            last_id = last_element["id"] + 1 if last_element else 0
            task = {
                "id": last_id,
                "transactions": transactions, 
                "prefix": current_prefix,
                "random_num_max": 99999999,
                "last_hash": last_element["hash"] if last_element else ""
            }
            # Guardo en Redis el prefijo requerido para este bloque:
            redis_utils.post_task(last_id, current_prefix)
            
            # Encolar en RabbitMQ en el topic
            channel.basic_publish(exchange='blockchain_challenge', routing_key='blocks', body=json.dumps(task))
            print(f"Encolando tarea para los workers: {task}")
            with time_challenge_initiate_lock:
                time_challenge_initiate = datetime.now(timezone.utc)
        else:
            print(f"No hay transacciones por el momento.")
        
        time.sleep(30)  # Cambiar a 60



@app.route("/solved_task", methods=["POST"])
def solved_task():
    global prefix
    global time_challenge_initiate
    global time_challenge_terminated
    global redis_utils
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se proporcionaron datos.'}), 400
        
        print("Worker data: ",data)

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
        prefijo = redis_utils.get_task(block_id)
        if not received_hash.startswith(prefijo):
            return jsonify({'error': 'El hash no tiene el prefijo requerido.'}), 400

        last_element = redis_utils.get_latest_element()
        if last_element:
            current_hash = last_element['hash']
        else:
            current_hash = ""

        combined_data = f"{number}{transactions}{current_hash}"
        hash_calculado = calcular_hash(combined_data)

        print(f"Hash recibido: {received_hash}")
        print(f"Hash calculado localmente: {hash_calculado}")

        if received_hash != hash_calculado:
            return jsonify({'error': 'Hash invalido. Descartado.'}), 400
                
        block = {
            "id": block_id,
            "hash": received_hash,
            "transactions": transactions,
            "prefix": prefijo,
            "number": number,   # nonce
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_hash": current_hash
        }

        redis_utils.post_message(message=block)

        # Calculo el prefijo para el próximo bloque
        time_challenge_terminated = datetime.now(timezone.utc)#.isoformat()
        time_difference = (time_challenge_terminated - time_challenge_initiate).total_seconds()

        with prefix_lock:
            if time_difference > 300:
                prefix -= "0"
            elif time_difference < 240:
                prefix += "0"
        print(f"""
---------------------------------------------------------------------
---------------------------------------------------------------------
---------------------------------------------------------------------
TIEMPO dif: {time_difference}
TIME CHALLENGE INITIATE: {time_challenge_initiate}
TIME CHALLENGE TERMINTATED: {time_challenge_terminated}
PREFIJO: {prefix}
---------------------------------------------------------------------
---------------------------------------------------------------------
---------------------------------------------------------------------
""")
        return jsonify({"message": "Transaccion procesada.", "data": block}), 200
    except Exception as e:
        return jsonify({"error": e}), 500

if __name__ == "__main__":
    # Configuración de Redis
    redis_host = 'redis'
    redis_port = 6379
    redis_db = 0
    # Configuración de RabbitMQ
    rabbitmq_host = 'rabbitmq'
    rabbitmq_port = 5672
    rabbitmq_queue = 'transactions'
    rabbitmq_exchange = 'blockchain_challenge'
    connected_redis = False
    while not connected_redis:
        try:
            connected_redis = False
            redis_client = redis.StrictRedis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)
            connected_redis = True
            print("Conectado a Redis")
        except Exception as e:
            print(f"No se pudo conectar a Redis: {e}")
            print("Reintentando en 3 segundos...")
            time.sleep(3)
    connected_rabbit = False
    while not connected_rabbit:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbitmq_host, port=rabbitmq_port))
            channel = connection.channel()
            # Crear cola
            channel.queue_declare(queue=rabbitmq_queue, durable=True)
            # Crear exchange tipo topic
            channel.exchange_declare(exchange=rabbitmq_exchange, exchange_type='topic', durable=True)
            connected_rabbit = True
            print("Conectado a RabbitMQ!")
        except Exception as e:
            print(f"Error connectando a RabbitMQ: {e}")
            print("Reintentando en 3 segundos...")
            time.sleep(3)

    thread = threading.Thread(target=task_building, daemon=True)
    # thread.daemon = True  # Permitir que el hilo se cierre cuando el programa principal termine
    thread.start()
    app.run(debug=True, port=5000, host="0.0.0.0")