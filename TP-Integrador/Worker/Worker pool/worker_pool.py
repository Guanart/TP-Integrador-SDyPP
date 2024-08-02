from datetime import datetime, timezone
import json
import random
import time
from flask import Flask, request, jsonify
import threading
import pika
import requests

app = Flask(__name__)

# Cambiar
id = random.randint(0,1000000)
ch_rabbit = None
method_rabbit = None
workers_conectados = []
resuelto = False




@app.route('/alive', methods=["POST"])
def receive_keep_alive():
    global workers_conectados
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se proporcionaron datos.'}), 400

        if "id" not in data:
            return jsonify({"error": "Worker id no proporcionado"}), 400
        
        if all(worker_registered["id"] != data["id"] for worker_registered in workers_conectados):
            workers_conectados.append({
                "id": data["id"],
                'last_keep_alive': datetime.now(timezone.utc),
                'missed_keep_alives': 0
            })
            message = {"message": "Worker registrado correctamente."}
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

def divisor_task(ch, method, properties, body):
    global workers_conectados
    global ch_rabbit 
    global method_rabbit
    global resuelto

    ch.basic_ack(delivery_tag=method.delivery_tag)
    ch_rabbit = ch
    method_rabbit = method
    resuelto = False
    data = json.loads(body)
    print(f"Message received")


    start_time = time.time()
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

def post_result(data):
    url = "http://coordinator:5000/solved_task"
    try:
        response = requests.post(url, json=data)
        print("Post response:", response.text)
    except requests.exceptions.RequestException as e:
        print("Failed to send POST request:", e)

@app.route('/solved_task', methods=["POST"])
def resend_result():
    global method_rabbit
    global ch_rabbit
    global resuelto

    if not resuelto:
        data = request.get_json()
        post_result(data)
        resuelto = True
        return jsonify({"message": "Bloque enviado a la Blockchain.", "data": data}), 200
    return jsonify({"error": "Tarea ya resuelta"}), 400

def send_keep_alive():
    global id
    url = "http://keep-alive-server:5001/alive"
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

def main():
    # Configuración de RabbitMQ
    consume_rabbitmq_host = 'rabbitmq'
    consume_rabbitmq_port = 5672
    consume_connected_rabbit = False
    while not consume_connected_rabbit:
        try:
            consume_connection = pika.BlockingConnection(pika.ConnectionParameters(host=consume_rabbitmq_host, port=consume_rabbitmq_port, credentials=pika.PlainCredentials('guest', 'guest'), heartbeat=0))
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
    # CONECTARSE AL RABBIT MQ DONDE SE PUBLICAN LAS TASKS PARA LOS WORKERS:
    rabbitmq_host = 'rabbitmq-worker-pool'
    rabbitmq_port = 5673
    rabbitmq_exchange = 'blockchain_challenge'
    connected_rabbit = False
    while not connected_rabbit:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbitmq_host, port=rabbitmq_port, heartbeat=0))
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
    data = {
        "id": id,
        "type": "gpu"
    }
    url = "http://keep-alive-server:5001/alive"
    registered_coordinator = False
    while not registered_coordinator:
        try:
            response = requests.post(url, json=data)
            if response.status_code == 200:
                print("Connected to Keep Alive Server")
                print(response.text)
                registered_coordinator = True
            else:
                print("Error to connect to keep alive server")
                print(response.status_code + response.text)
                time.sleep(3)
        except requests.exceptions.RequestException as e:
            print("Failed to send POST request:", e)
    threading.Thread(target=send_keep_alive, daemon=True).start()

    # CONECTARSE A RABBIT DE BLOCKCHAIN Y EMPEZAR A CONSUMIR:
    threading.Thread(target=main).start()
    #main()

    # COMENZAR A FUNCIONAR COMO SERVER KEEP ALIVE PARA LOS WORKERS QUE SE CONECTEN:
    threading.Thread(target=workers_with_live).start()
    app.run(host="0.0.0.0", port=5002)