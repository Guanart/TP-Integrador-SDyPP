from datetime import datetime
import threading
from flask import Flask, request, jsonify
import pika
import json
import time
import redis
import random
import hashlib
import os
import sys

app = Flask(__name__)
transaction_block_list = []

@app.route('/')
def index():
    return f"Coordinador funcionando!"

@app.route('/transaction', methods=['POST'])
def transaction():
    pass

@app.route('/status', methods=['GET'])
def status():
    pass

def block_building():
    global transaction_block_list
    while True:
        time.sleep(3)

@app.route("/solved_task", methods=["POST"])
def solved_task():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No se proporcionaron datos'}), 400
    number = data.get("number")
    string = data.get("transactions_string")
    received_hash = data.get("hash")
    current_hash = "hash" #este se saca de redis
    if received_hash != str(current_hash):
        return jsonify({'error': 'Datos inconsistentes'}), 400
    transaction_block = {
        "hash": received_hash,
        "transactions": string,
        "timestamp": datetime.utcnow().isoformat(),
        "prev_hash": current_hash
    }
    # block_id = redis_client.incr('block_id')
    # redis_client.hmset(f"block:{block_id}", transaction_block)
    return jsonify({"status": "transaccion procesada", "id": 1, "data": transaction_block}), 200

if __name__ == "__main__":
    # # Configuración de Redis
    # redis_host = 'localhost'
    # redis_port = 6379
    # redis_db = 0

    # # Conexión a Redis
    # redis_client = redis.StrictRedis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)

    # Configuración de RabbitMQ
    # rabbitmq_host = 'localhost'
    # rabbitmq_port = 5672
    # rabbitmq_queue = 'my_queue'
    # rabbitmq_exchange = 'my_topic_exchange'
    # rabbitmq_routing_key = 'my.routing.key'

    # # Conexión a RabbitMQ
    # connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbitmq_host, port=rabbitmq_port))
    # channel = connection.channel()

    # # Crear cola
    # channel.queue_declare(queue=rabbitmq_queue, durable=True)

    # # Crear intercambio tipo tópico
    # channel.exchange_declare(exchange=rabbitmq_exchange, exchange_type='topic')

    # # Vincular la cola al intercambio
    # channel.queue_bind(exchange=rabbitmq_exchange, queue=rabbitmq_queue, routing_key=rabbitmq_routing_key)
    thread = threading.Thread(target=block_building)
    thread.daemon = True  # Permitir que el hilo se cierre cuando el programa principal termine
    thread.start()
    app.run(debug=True)