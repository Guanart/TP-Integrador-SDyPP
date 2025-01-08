from datetime import datetime, timezone
import json
import os
import random
import time
from flask import Flask, request, jsonify
import threading
import pika
import requests
import uuid

app = Flask(__name__)

id = -1 # ID del worker-pool (como se identifica con el keepalive server de la blockchain)
workers_conectados = [] # Lista de workers conectados al pool
resuelto = False  # Variable para saber si la tarea ya fue resuelta
conectado_keepalive = False # Variable para saber si el worker-pool está conectado al keep-alive-server
channel = None
connection = None
sender_keepalive = False

# VARIABLES DE ENTORNO
POOL_RABBITMQ_HOST = os.environ.get("POOL_RABBITMQ_HOST")
POOL_RABBITMQ_PORT = os.environ.get("POOL_RABBITMQ_PORT")
POOL_RABBITMQ_USER = os.environ.get("POOL_RABBITMQ_USER")
POOL_RABBITMQ_PASSWORD = os.environ.get("POOL_RABBITMQ_PASSWORD")
CONSUME_RABBITMQ_HOST = os.environ.get("CONSUME_RABBITMQ_HOST")
CONSUME_RABBITMQ_PORT = os.environ.get("CONSUME_RABBITMQ_PORT")
CONSUME_RABBITMQ_USER = os.environ.get("CONSUME_RABBITMQ_USER")
CONSUME_RABBITMQ_PASSWORD = os.environ.get("CONSUME_RABBITMQ_PASSWORD")
KEEP_ALIVE_SERVER_HOST = os.environ.get("KEEP_ALIVE_SERVER_HOST")
KEEP_ALIVE_SERVER_PORT = os.environ.get("KEEP_ALIVE_SERVER_PORT")
COORDINATOR_HOST = os.environ.get("COORDINATOR_HOST")
COORDINATOR_PORT = os.environ.get("COORDINATOR_PORT")

# FUNCIÓN PARA GENERAR UN ID ÚNICO PARA LOS WORKERS QUE SE CONECTAN
def generate_id():
    return uuid.uuid4()

# ENDPOINT PARA RECIBIR KEEP-ALIVE DE LOS WORKERS
@app.route('/alive', methods=["POST"])
def receive_keep_alive():
    global workers_conectados
    global conectado_keepalive
    global sender_keepalive

    try:
        # Verificar que se hayan proporcionado datos
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se proporcionaron datos.'}), 400
        # Verificar que se haya proporcionado el ID del worker
        if "id" not in data:
            return jsonify({"error": "Worker id no proporcionado"}), 400
        if data["id"] == -1: # Si el worker es nuevo, se agrega al pool
            id_generado = str(generate_id())
            workers_conectados.append({
                "id": id_generado,
                'last_keep_alive': datetime.now(timezone.utc),
                'missed_keep_alives': 0
            })
            message = {"message": "Worker registrado correctamente.", "id": id_generado}
            print("Worker registrado correctamente. ID: ", id_generado)
            print()
            # Si el pool no estaba conectado al keep-alive server se conecta (ya que ahora si hay workers conectados)
            if not conectado_keepalive:
                connect_keep_alive_server()
                if not sender_keepalive:
                    sender_keepalive = True
                    threading.Thread(target=send_keep_alive, daemon=True).start()
        elif (data["id"] != -1) and all(worker_registered["id"] != data["id"] for worker_registered in workers_conectados):
            # Si se envió un ID que no está registrado, se rechaza
            return jsonify({"error": "Worker id no registrado"}), 400
        else:
            # Si se envió un ID distinto de -1 y ya está registrado, se acepta
            message = {"message": "Mensaje keep_alive recibido correctamente"}
        # Actualizar el último keep-alive del worker
        for worker in workers_conectados:
            if worker["id"] == data["id"]:
                worker["last_keep_alive"] = datetime.now(timezone.utc)
                break
        return jsonify(message), 200
    except Exception as e:
        return jsonify(e)

# FUNCIÓN PARA REMOVER UN WORKER DEL POOL
def remove_worker_by_id(worker_id):
    global workers_conectados
    workers_conectados = [worker for worker in workers_conectados if worker["id"] != worker_id]

# FUNCIÓN CICLO PARA VERIFICAR WORKERS CON VIDA
def workers_with_live():
    global workers_conectados
    global conectado_keepalive

    while True:
        print("Comprobando workers activos...")
        print()
        now = datetime.now(timezone.utc)
        for worker in workers_conectados:
            time_diference = (now - worker["last_keep_alive"]).total_seconds()
            # Si pasaron 10 segundos sin recibir un keep-alive, se agrega un keepalive perdido
            if time_diference >= 10:
                worker["missed_keep_alives"]+=1
            # Si pasaron menos de 10 segundos, se reinicia la cantidad de keepalives perdidos
            else:
                worker["missed_keep_alives"]=0
            # Si un worker tiene 3 keepalives perdidos, se elimina de la lista de workers conectados
            if worker["missed_keep_alives"]==3:
                remove_worker_by_id(worker["id"])
        # Si no hay workers conectados y el pool estaba conectado al keep-alive server, se desconecta
        if len(workers_conectados) == 0 and conectado_keepalive:
            conectado_keepalive = False
        # Timer para volver a comprobar los workers
        time.sleep(10)

# FUNCIÓN PARA DIVIDIR LA TAREA DE MINADO Y ENVIARLA A LOS WORKERS
def divisor_task(ch, method, properties, body):
    global workers_conectados
    global resuelto
    global channel

    data = json.loads(body)
    print(f"Tarea recibida")
    print()
    resuelto = False

    # Verificar que haya workers conectados al pool
    if (len(workers_conectados) == 0):
        print("Todavía no hay workers conectados al pool, tarea descartada")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    # Si hay workers conectados, dividir la tarea
    else:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        print("Dividiendo la tarea...")
        # Dividir la tarea en partes iguales para cada worker
        num_max = data["num_max"]
        num_workers = len(workers_conectados)
        range_size = num_max // num_workers
        # Calcular el sobrante que no se divide exactamente
        remainder = num_max % num_workers
        start = data["num_min"]
        # Imprimir workers conectados al pool que recibirán la tarea
        print("Workers conectados al pool que recibirán la tarea: "+str(workers_conectados))
        print()
        # Enviar la tarea a cada worker
        for i in range(len(workers_conectados)):
            worker = workers_conectados[i]
            end = start + range_size + (remainder if i == len(workers_conectados)-1 else 0)
            data["num_min"] = start
            data["num_max"] = end
            print(f"Enviando tarea al worker {worker['id']} con rango: [{start} - {end}]")
            print()
            # Publicar el mensaje
            while True:
                try:
                    channel.basic_publish(exchange='blockchain_challenge', routing_key=f'{worker["id"]}', body=body)
                    print("Mensaje publicado exitosamente")
                    print()
                    break  # Salir del bucle si el mensaje se publica exitosamente
                except Exception as e:
                    print(f"Error al publicar el mensaje: {e}")
                    print("Reintentando publicar el mensaje...")
                    print()
                    reconnect_rabbitmq()
            start = end + 1 # Actualizar el inicio para la siguiente tarea

# FUNCIÓN PARA ENVIAR LA TAREA RESUELTA AL COORDINADOR
def post_result(data):
    url = f"http://{COORDINATOR_HOST}:{COORDINATOR_PORT}/solved_task"
    try:
        print("Un worker ha resuelto la tarea.")
        print()
        response = requests.post(url, json=data)
        print("Post response: ", response.text)
        print()
    except requests.exceptions.RequestException as e:
        print("Failed to send POST request:", e)
        print()

# ENDPOINT PARA RECIBIR LA TAREA RESUELTA DE LOS WORKERS
@app.route('/solved_task', methods=["POST"])
def resend_result():
    global resuelto

    # Verificar que la tarea no haya sido resuelta
    if not resuelto:
        resuelto = True
        data = request.get_json()
        post_result(data)
        return jsonify({"message": "Bloque enviado a la Blockchain.", "data": data}), 200
    return jsonify({"error": "Tarea ya resuelta"}), 400

# FUNCIÓN CICLO PARA ENVIAR KEEP-ALIVE AL SERVER
def send_keep_alive():
    global id
    global conectado_keepalive

    url = f"http://{KEEP_ALIVE_SERVER_HOST}:{KEEP_ALIVE_SERVER_PORT}/alive"
    data = {
        "id": id,
        "type": "gpu",
    }
    while True:
        try:
            # Verificar si el worker sigue conectado al keep-alive server
            if (conectado_keepalive):
                print("Enviando keep-alive...")
                response = requests.post(url, json=data)
                print("Respuesta del keep-alive-server:", response.text)
            time.sleep(7)
        except requests.exceptions.RequestException as e:
            print("Falló al hacer POST al keep-alive-server:", e)

# FUNCIÓN PARA CONECTARSE AL KEEP-ALIVE SERVER
def connect_keep_alive_server():
    global id
    global conectado_keepalive

    data = {
        "id": id,
        "type": "gpu"
    }
    url = f"http://{KEEP_ALIVE_SERVER_HOST}:{KEEP_ALIVE_SERVER_PORT}/alive"
    while not conectado_keepalive:
        try:
            response = requests.post(url, json=data)
            if response.status_code == 200:
                print("Connected to Keep Alive Server")
                print(response.text)
                id = response.json()["id"]
                conectado_keepalive = True
            else:
                print("Error to connect to keep alive server")
                print(response.status_code + response.text)
                time.sleep(3)
        except requests.exceptions.RequestException as e:
            print("Failed to send POST request:", e)

# FUNCIÓN PARA CONECTAR CON RABBITMQ DE LA BLOCKCHAIN
def main():
    while True:
        try:
            # Crear nueva conexión y canal
            consume_connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=CONSUME_RABBITMQ_HOST,
                    port=CONSUME_RABBITMQ_PORT,
                    credentials=pika.PlainCredentials(CONSUME_RABBITMQ_USER, CONSUME_RABBITMQ_PASSWORD),
                    heartbeat=3600
                )
            )
            consume_channel = consume_connection.channel()
            consume_channel.exchange_declare(exchange='blockchain_challenge', exchange_type='topic', durable=True)
            result = consume_channel.queue_declare('', exclusive=True)
            consume_queue_name = result.method.queue
            consume_channel.queue_bind(exchange='blockchain_challenge', queue=consume_queue_name, routing_key='tasks')

            print("Conectado a RabbitMQ. Esperando mensajes...")
            consume_channel.basic_consume(queue=consume_queue_name, on_message_callback=divisor_task, auto_ack=False)
            consume_channel.start_consuming()

        except KeyboardInterrupt:
            print("Consumption stopped by user.")
            consume_connection.close()
            break

        except (pika.exceptions.AMQPConnectionError, pika.exceptions.StreamLostError) as e:
            print(f"Error de conexión: {e}. Reintentando en 5 segundos...")
            time.sleep(5)

# FUNCIÓN PARA RECONECTAR CON RABBITMQ (DEL POOL)
def reconnect_rabbitmq():
    global channel
    global connection

    while connection is None or not connection.is_open:
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=POOL_RABBITMQ_HOST,
                    port=POOL_RABBITMQ_PORT, 
                    credentials=pika.PlainCredentials(POOL_RABBITMQ_USER, POOL_RABBITMQ_PASSWORD), 
                    heartbeat=3600
                )
            )
            channel = connection.channel()
            channel.exchange_declare(exchange='blockchain_challenge', exchange_type='topic', durable=True)
            print("Reconectado a RabbitMQ (worker-pool)!")
        except Exception as e:
            print(f"Error al reconectar con RabbitMQ (worker-pool): {e}")
            print("Reintentando en 3 segundos...")
            time.sleep(3)

if __name__ == "__main__": 
    # CONECTARSE AL RABBITMQ DONDE SE PUBLICAN LAS TASKS PARA LOS WORKERS (rabbit del pool de workers):
    reconnect_rabbitmq()

    # CONECTARSE AL RABBITMQ DE LA BLOCKCHAIN PARA CONSUMIR LAS TASKS:
    threading.Thread(target=main).start()
    
    # COMENZAR A FUNCIONAR COMO SERVER KEEP ALIVE PARA LOS WORKERS QUE SE CONECTEN:
    threading.Thread(target=workers_with_live).start()
    app.run(host="0.0.0.0", port=5002)