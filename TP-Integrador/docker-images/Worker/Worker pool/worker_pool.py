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

# Cambiar
id = -1
workers_conectados = []
resuelto = False

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

def generate_id():
    return uuid.uuid4()

# Funcionamos como keep-alive-server para mantener registro de cuantos workers conectados tenemos
@app.route('/alive', methods=["POST"])
def receive_keep_alive():
    global workers_conectados
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se proporcionaron datos.'}), 400

        if "id" not in data:
            return jsonify({"error": "Worker id no proporcionado"}), 400
        
        if data["id"] == -1:
            id_generado = str(generate_id())
            workers_conectados.append({
                "id": id_generado,
                'last_keep_alive': datetime.now(timezone.utc),
                'missed_keep_alives': 0
            })
            message = {"message": "Worker registrado correctamente.", "id": id_generado}
        elif (data["id"] != -1) and all(worker_registered["id"] != data["id"] for worker_registered in workers_conectados):
            return jsonify({"error": "Worker id no registrado"}), 400
        else:
            message = {"message": "Mensaje keep_alive recibido correctamente"}
        
        for worker in workers_conectados:
            if worker["id"] == data["id"]:
                worker["last_keep_alive"] = datetime.now(timezone.utc)
                break
        return jsonify(message), 200
    except Exception as e:
        return jsonify(e)
    
def remove_worker_by_id(worker_id):
    global workers_conectados
    workers_conectados = [worker for worker in workers_conectados if worker["id"] != worker_id]

def workers_with_live():
    global workers_conectados
    while True:
        print("Comprobando workers activos...")
        now = datetime.now(timezone.utc)
        for worker in workers_conectados:
            time_diference = (now - worker["last_keep_alive"]).total_seconds()
            if time_diference >= 10:
                worker["missed_keep_alives"]+=1
            else:
                worker["missed_keep_alives"]=0
            if worker["missed_keep_alives"]==3:
                remove_worker_by_id(worker["id"])
        time.sleep(10)

# Función al consumir una tarea:
def divisor_task(ch, method, properties, body):
    global workers_conectados
    global resuelto

    resuelto = False
    data = json.loads(body)
    print(f"Tarea recibida")

    if (len(workers_conectados) == 0):
        print("Todavía no hay workers conectados al pool, tarea descartada")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    else:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        print("Dividiendo la tarea...")
        
        num_max = data["num_max"]
        num_workers = len(workers_conectados)
        range_size = num_max // num_workers
        # Calcular el sobrante que no se divide exactamente
        remainder = num_max % num_workers
        start = data["num_min"]
        

        for i in range(len(workers_conectados)):
            worker = workers_conectados[i]
            end = start + range_size + (remainder if i == len(workers_conectados)-1 else 0)
            data["num_min"] = start
            data["num_max"] = end
            channel.basic_publish(exchange='blockchain_challenge', routing_key=f'{worker["id"]}', body=json.dumps(data))
            start = end + 1

# Cuando un worker responde, mandamos su solución al coordinador
def post_result(data):
    url = f"http://{COORDINATOR_HOST}:{COORDINATOR_PORT}/solved_task"
    try:
        response = requests.post(url, json=data)
        print("Post response:", response.text)
    except requests.exceptions.RequestException as e:
        print("Failed to send POST request:", e)

# Los workers que se conectan al pool mandan la tarea resuelta a este, no al coordinador
@app.route('/solved_task', methods=["POST"])
def resend_result():
    global resuelto
    if not resuelto:
        resuelto = True
        data = request.get_json()
        post_result(data)
        return jsonify({"message": "Bloque enviado a la Blockchain.", "data": data}), 200
    return jsonify({"error": "Tarea ya resuelta"}), 400

# Función igual a la de los workers para mandar keep-alive al server (ya que se trata como un worker único)
def send_keep_alive():
    global id
    url = f"http://{KEEP_ALIVE_SERVER_HOST}:{KEEP_ALIVE_SERVER_PORT}/alive"
    data = {
        "id": id,
        "type": "gpu",
    }
    while True:
        try:
            print("Enviando keep-alive...")
            response = requests.post(url, json=data)
            print("Respuesta del keep-alive-server:", response.text)
            time.sleep(7)
        except requests.exceptions.RequestException as e:
            print("Falló al hacer POST al keep-alive-server:", e)

def connect_keep_alive_server():
    global id
    data = {
        "id": id,
        "type": "gpu"
    }
    url = f"http://{KEEP_ALIVE_SERVER_HOST}:{KEEP_ALIVE_SERVER_PORT}/alive"
    registered_coordinator = False
    while not registered_coordinator:
        try:
            response = requests.post(url, json=data)
            if response.status_code == 200:
                print("Connected to Keep Alive Server")
                print(response.text)
                registered_coordinator = True
                id = response.json()["id"]
            else:
                print("Error to connect to keep alive server")
                print(response.status_code + response.text)
                time.sleep(3)
        except requests.exceptions.RequestException as e:
            print("Failed to send POST request:", e)
    threading.Thread(target=send_keep_alive, daemon=True).start()


def main():
    # Configuración de RabbitMQ
    consume_connected_rabbit = False
    while not consume_connected_rabbit:
        try:
            consume_connection = pika.BlockingConnection(pika.ConnectionParameters(host=CONSUME_RABBITMQ_HOST, port=CONSUME_RABBITMQ_PORT, credentials=pika.PlainCredentials(CONSUME_RABBITMQ_USER, CONSUME_RABBITMQ_PASSWORD), heartbeat=3600))
            consume_channel = consume_connection.channel()
            consume_channel.exchange_declare(exchange='blockchain_challenge', exchange_type='topic', durable=True)
            result = consume_channel.queue_declare('', exclusive=True)
            consume_queue_name = result.method.queue
            consume_channel.queue_bind(exchange='blockchain_challenge', queue=consume_queue_name, routing_key='tasks')
            consume_connected_rabbit = True
            print("Ya se encuentra conectado a RabbitMQ! (rabbit de la blockchain)")
        except Exception as e:
            print(f"Error connectando a RabbitMQ (rabbit blockchain): {e}")
            print("Reintentando en 3 segundos...")
            time.sleep(3)
    
    consume_channel.basic_consume(queue=consume_queue_name, on_message_callback=divisor_task, auto_ack=False)
    print('Waiting for messages. To exit press CTRL+C')
    try:
        consume_channel.start_consuming()
    except KeyboardInterrupt:
        print("Consumption stopped by user.")
        consume_connection.close()
        print("Connection closed.")

if __name__ == "__main__": 
    # CONECTARSE AL RABBITMQ DONDE SE PUBLICAN LAS TASKS PARA LOS WORKERS (rabbit del pool de workers):
    rabbitmq_exchange = 'blockchain_challenge'
    connected_rabbit = False
    while not connected_rabbit:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=POOL_RABBITMQ_HOST, port=POOL_RABBITMQ_PORT, credentials=pika.PlainCredentials(POOL_RABBITMQ_USER, POOL_RABBITMQ_PASSWORD), heartbeat=3600))
            channel = connection.channel()
            channel.exchange_declare(exchange=rabbitmq_exchange, exchange_type='topic', durable=True)
            connected_rabbit = True
            print("Conectado a RabbitMQ (worker-pool)!")
        except Exception as e:
            print (e)
            print(f"Error al conectar con RabbitMQ (worker-pool): {e}")
            print("Reintentando en 3 segundos...")
            time.sleep(3)

    # CONECTARSE AL KEEP ALIVE SERVER DE LA BLOCKCHAIN:
    connect_keep_alive_server()

    # CONECTARSE A RABBIT DE BLOCKCHAIN Y EMPEZAR A CONSUMIR:
    threading.Thread(target=main).start()

    # COMENZAR A FUNCIONAR COMO SERVER KEEP ALIVE PARA LOS WORKERS QUE SE CONECTEN:
    threading.Thread(target=workers_with_live).start()
    app.run(host="0.0.0.0", port=5002)