from datetime import datetime, timezone
import os
import threading
from flask import Flask, request, jsonify
import pika
import json
import time
import redis
import hashlib
from redis_utils import RedisUtils

app = Flask(__name__)
prefix = "000"
last_task = None
last_id = 0
lock = threading.Lock()
connection_rabbit = None
channel = None
redis_client = None
redis_utils = None
time_challenge_initiate: datetime = datetime.now(timezone.utc)

# FUNCIÓN PARA CALCULAR EL HASH
def calcular_hash(data):
    hash = hashlib.md5()
    hash.update(data.encode('utf-8'))
    return hash.hexdigest()

# ENDPOINT PARA REALIZAR TRANSACCIONES
@app.route('/transaction', methods=['POST'])
def transaction():
    try:
        # Verificar si se proporcionaron datos
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se proporcionaron datos.'}), 400
        # Verificar si se proporcionaron todos los campos necesarios
        required_fields = ['user_from', 'user_to', 'amount']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Faltan uno o más campos necesarios.'}), 400
        # Imprimir mensaje recibido
        print(f"Transacción recibida: {data}")
        print()
        # Encolar la transacción en RabbitMQ
        channel.basic_publish(exchange='', routing_key='transactions', body=json.dumps(data))
        return jsonify({'message': 'Transacción recibida y encolada en RabbitMQ.', "data": data}), 200
    except Exception as e:
        return jsonify(e)

# ENDPOINT PARA OBTENER EL ESTADO DEL COORDINADOR
@app.route('/status', methods=['GET'])
def status():
    global redis_client, connection_rabbit
    try:
        # Verificar conexión a Redis
        redis_client.ping() 
        # Verificar conexión a RabbitMQ
        if connection_rabbit.is_open: 
            return jsonify({'message': 'running'}), 200
        else:
            return jsonify({'error': 'No se está conectado a RabbitMQ'}), 500
    except redis.ConnectionError:
        return jsonify({'error': 'No se está conectado a Redis'}), 500
    except pika.exceptions.AMQPConnectionError:
        return jsonify({'error': 'No se está conectado a RabbitMQ'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# FUNCIÓN PARA POSTEAR UNA TAREA PARA LOS WORKERS
def postear_task(last_element):
    global last_id
    global last_task
    global time_challenge_initiate

    # Obtener las transacciones de la cola de RabbitMQ
    transactions = []
    while True:
        method_frame, header_frame, body = channel.basic_get(queue='transactions', auto_ack=False)
        if method_frame:
            # Agregar la transacción al array de transacciones
            transactions.append(json.loads(body))
            print("Transaccion recibida de la cola de RabbitMQ")
            # Enviar ACK del mensaje recibido
            channel.basic_ack(delivery_tag=method_frame.delivery_tag)
        else:
            print()
            break  # No hay más mensajes para recibir
        
    if transactions:
        # Crear la tarea
        task = {
            "id": last_id,
            "transactions": transactions, 
            "prefix": prefix,
            "num_min": 0,
            "num_max": 99999999,
            "last_hash": last_element["hash"] if last_element else ""
        }
        # Guardar en Redis la tarea (para conocer la ulima tarea posteada):
        redis_utils.post_task(last_id, task)   
        last_task = task
        # Postear la tarea en el topic de RabbitMQ
        print("Se va a publicar una tarea para los workers")
        print()
        channel.basic_publish(exchange='blockchain_challenge', routing_key='tasks', body=json.dumps(task))
        print(f"Encolando tarea para los workers. Descripcion de la tarea: {task}")
        print()
        # Iniciar el timer
        time_challenge_initiate = datetime.now(timezone.utc)
    else:
        print(f"No hay transacciones por el momento.")
        print()

# FUNCIÓN PARA REPOSTEAR UNA TAREA PARA LOS WORKERS 
# (CUANDO PASA UN TIEMPO Y NINGUN WORKER PUBLICÓ UNA SOLUCIÓN)
def repostear_task():
    global last_task
    global time_challenge_initiate

    # Guardar en Redis la tarea:
    redis_utils.post_task(last_id, last_task)   
    # Postear la tarea en el topic de RabbitMQ
    channel.basic_publish(exchange='blockchain_challenge', routing_key='tasks', body=json.dumps(last_task))
    print(f"Encolando tarea para los workers. Descripcion de la tarea: {last_task}")
    print()
    # Iniciar el timer
    time_challenge_initiate = datetime.now(timezone.utc)

# FUNCIÓN CICLO PARA GENERAR TAREAS
def task_building():
    global prefix
    global time_challenge_initiate
    global redis_utils
    global last_task
    global last_id

    # Comprobar estar conectado Redis y RabbitMQ
    while connect_redis() and connect_rabbitmq():
        print("Comprobando si hay transacciones para generar task...")
        print()
        # Obtener último bloque de la blockchain
        last_element = redis_utils.get_latest_element() 
        # Aumentar el last_id con respecto al ID del ultimo bloque de la blockchain
        last_id = last_element["id"] + 1 if last_element else 0 

        # Si la ultima tarea que se publicó es igual al ultimo id, significa que ningun worker ha publicado la solución
        if last_task != None and last_task['id'] == last_id:
            # Obtengo la diferencia de tiempo
            time_difference = (datetime.now(timezone.utc) - time_challenge_initiate).total_seconds()
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
        
        # Llamar a la función para postear tarea
        postear_task(last_element)                
        time.sleep(30)  # Cambiar a 60

# ENDPOINT PARA RECIBIR SOLUCIONES DE LOS WORKERS
@app.route("/solved_task", methods=["POST"])
def solved_task():
    global redis_utils
    
    try:
        # Verificar si se proporcionaron datos
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se proporcionaron datos.'}), 400
        # Imprimir solución recibida
        print(f"Un Worker envió su solución:\n{data}")
        print()
        # Verificar si se proporcionaron todos los campos necesarios
        required_fields = ['id', 'number', 'transactions', 'hash']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Faltan uno o más campos necesarios.'}), 400
        # Verificar si el bloque ya existe
        block_id = data.get("id")
        if redis_utils.exists_id(block_id):
            return jsonify({'error': 'El bloque ya existe.'}), 400
        # Comparar el prefijo de la tarea con el que envió el worker
        received_hash = data.get("hash")
        prefijo = redis_utils.get_task(block_id)["prefix"]
        if not received_hash.startswith(prefijo):
            return jsonify({'error': 'El hash no tiene el prefijo requerido.'}), 400
        # Invocar a la sección crítica (para agregar el bloque a la blockchain)
        respuesta, codigo_estado = seccion_critica(data)
        return respuesta, codigo_estado
    except Exception as e:
        return jsonify({"error": e}), 500

# SECCIÓN CRÍTICA (DONDE SE DECIDE SI GUARDAR EL BLOQUE EN BLOCKCHAIN)
def seccion_critica(data):
    global prefix
    global time_challenge_initiate
    global redis_utils
    global lock
    
    with lock:
        # Verificar si el bloque ya existe
        block_id = block["id"]
        if redis_utils.exists_id(block_id):
            return jsonify({'error': 'El bloque ya existe.'}), 400
        # Obtener el ultimo hash de la blockchain
        last_element = redis_utils.get_latest_element()
        if last_element:
            current_hash = last_element['hash']
        else:
            current_hash = ""
        # Obtener el nonce y las transacciones del bloque
        number = data.get("number") # Nonce
        transactions = data.get("transactions")
        # Comprobar si el hash recibido está bien calculado
        hash_calculado = calcular_hash(f"{number}{len(transactions)}{current_hash}")
        received_hash = data.get("hash")
        print(f"Hash recibido: {received_hash}")
        print(f"Hash calculado localmente: {hash_calculado}")
        print()
        if received_hash != hash_calculado:
            return jsonify({'error': 'Hash invalido. Descartado.'}), 400
        
        # Crear el bloque
        prefijo = redis_utils.get_task(block_id)["prefix"]
        block = {
            "id": block_id,
            "hash": received_hash,
            "transactions": transactions,
            "prefix": prefijo,
            "number": number,   # Nonce
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_hash": current_hash
        }
        # Guardar bloque en Redis
        redis_utils.post_message(message=block)
        # Calcular el prefijo para el próximo bloque
        time_difference = (datetime.now(timezone.utc) - time_challenge_initiate).total_seconds()
        if time_difference > 75 and len(prefix) > 1:
            prefix = prefix[:-1]  # Quitar un "0"
            print(f"NUEVO PREFIJO (disminuyo): {prefix}")
            print()
        elif time_difference < 30:
            prefix += "0"
            print(f"NUEVO PREFIJO (aumento): {prefix}")
            print()
        # Eliminar la tarea de Redis
        redis_utils.delete_task(block_id)
        return jsonify({"message": "Bloque añadido a la Blockchain."}), 200

# FUNCIÓN PARA CONECTAR CON REDIS
def connect_redis():
    # Configuración de Redis:
    global redis_client, redis_utils
    redis_host = os.environ.get("REDIS_HOST")
    redis_port = os.environ.get("REDIS_PORT")
    redis_db = os.environ.get("REDIS_DB")
    while redis_client is None or not redis_client.ping():
        try:
            redis_client = redis.StrictRedis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)
            redis_utils = RedisUtils(redis_client)
            print("Conectado a Redis")
            print()
            return True
        except Exception as e:
            print(f"No se pudo conectar a Redis: {e}")
            print("Reintentando en 5 segundos...")
            print()
            time.sleep(5)

# FUNCIÓN PARA CONECTAR CON RABBITMQ
def connect_rabbitmq():
    # Configuración de RabbitMQ
    global connection_rabbit, channel
    rabbitmq_host = os.environ.get("RABBITMQ_HOST")
    rabbitmq_port = os.environ.get("RABBITMQ_PORT")
    rabbitmq_user = os.environ.get("RABBITMQ_USER")
    rabbitmq_password = os.environ.get("RABBITMQ_PASSWORD")
    rabbitmq_queue = 'transactions'
    rabbitmq_exchange = 'blockchain_challenge'
    while connection_rabbit is None or not connection_rabbit.is_open:
        try:
            credentials = pika.PlainCredentials(rabbitmq_user, rabbitmq_password)
            parameters = pika.ConnectionParameters(host=rabbitmq_host, port=rabbitmq_port, credentials=credentials, heartbeat=0)
            connection_rabbit = pika.BlockingConnection(parameters)
            channel = connection_rabbit.channel()
            channel.queue_declare(queue=rabbitmq_queue, durable=True)
            channel.exchange_declare(exchange=rabbitmq_exchange, exchange_type='topic', durable=True)
            print("Conectado a RabbitMQ!")
            print()
            return True
        except Exception as e:
            print(f"Error al conectar con RabbitMQ: {e}")
            print("Reintentando en 5 segundos...")
            print()
            time.sleep(5)

# INICIO DE LA APLICACIÓN
if __name__ == "__main__":
    if connect_redis() and connect_rabbitmq():
        threading.Thread(target=task_building).start()
        app.run(host="0.0.0.0", port=5000)
