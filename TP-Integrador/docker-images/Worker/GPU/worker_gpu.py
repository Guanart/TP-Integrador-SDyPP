import os
import pika
import json
import minero_gpu
import requests
import time
import threading

id = -1
RABBITMQ_USER = os.environ.get("RABBITMQ_USER")
RABBITMQ_PASSWORD = os.environ.get("RABBITMQ_PASSWORD")
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST")
RABBITMQ_PORT = os.environ.get("RABBITMQ_PORT")
COORDINATOR_HOST = os.environ.get("COORDINATOR_HOST")
COORDINATOR_PORT = os.environ.get("COORDINATOR_PORT")
KEEPALIVE_HOST = os.environ.get("KEEPALIVE_HOST")
KEEPALIVE_PORT = os.environ.get("KEEPALIVE_PORT")
ES_WORKER_POOL = os.environ.get("ES_WORKER_POOL")
connection = None

def post_result(data):
    url = f"http://{COORDINATOR_HOST}:{COORDINATOR_PORT}/solved_task"
    try:
        response = requests.post(url, json=data)
        print("POST response:", response.text)
    except requests.exceptions.RequestException as e:
        print("Failed to send POST request:", e)

def on_message_received(ch, method, properties, body):
    data = json.loads(body)
    print(f"Tarea recibida")
    '''
    data = {
        "id": last_id,
        "transactions": transactions, 
        "prefix": prefix,
        "num_min": 0,
        "num_max": 99999999,
        "last_hash": last_element["hash"] if last_element else ""
    }
    '''
    start_time = time.time()
    print("Starting mining process...")
    
    resultado = minero_gpu.ejecutar_minero(data["num_min"], data["num_max"], data["prefix"], str(len(data['transactions'])) + data["last_hash"])
    processing_time = time.time() - start_time
    resultado = json.loads(resultado)

    data["hash"] = resultado['hash_md5_result']
    data["number"] = resultado["numero"]

    if (resultado):
        post_result(data)
        print(f"Resultado encontrado y posteado para el block con ID {data['id']} en {processing_time:.2f} segundos")
        ch.basic_ack(delivery_tag=method.delivery_tag)
    else:
        print()
        #print(f"No se encontró un Hash con ese máximo de números")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # Le indico que no pude, y que no reencole

def send_keep_alive():
    global id
    url = f"http://{KEEPALIVE_HOST}:{KEEPALIVE_PORT}/alive"
    data = {
        "id": id,
        "type": "gpu"
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
    url = f"http://{KEEPALIVE_HOST}:{KEEPALIVE_PORT}/alive"
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
    
"""
def on_message_received(ch, method, properties, body):
    print(f"Mensaje recibido de RABBITMQ: {json.loads(body)}")
    print("Haciendo como que proceso....")
    ch.basic_ack(delivery_tag=method.delivery_tag)
"""
def main():
    global connection

    while True:
        print("Ciclo while")
        print()
        try:
            if connection is None or not connection.is_open:
                connection = pika.BlockingConnection(
                    pika.ConnectionParameters(
                        host=RABBITMQ_HOST, 
                        port=RABBITMQ_PORT, 
                        credentials=pika.PlainCredentials(f'{RABBITMQ_USER}', f'{RABBITMQ_PASSWORD}'), 
                        heartbeat=0
                    )
                )
                channel = connection.channel()
                channel.exchange_declare(exchange='blockchain_challenge', exchange_type='topic', durable=True)
                result = channel.queue_declare('', exclusive=True)
                queue_name = result.method.queue
                #routing_key = f'{id}' if ES_WORKER_POOL else 'tasks'
                routing_key = 'tasks'
                channel.queue_bind(exchange='blockchain_challenge', queue=queue_name, routing_key=routing_key)
                print(f"Bindeando queue con Routing key: {routing_key}")
                channel.basic_consume(queue=queue_name, on_message_callback=on_message_received, auto_ack=False)
                print("PASÉ BASIC CONSUME")
                channel.start_consuming()

        except KeyboardInterrupt:
            print("Consumption stopped by user.")
            connection.close()
            break

        except (pika.exceptions.AMQPConnectionError, pika.exceptions.StreamLostError) as e:
            print(f"Error de conexión: {e}. Reintentando en 5 segundos...")
            time.sleep(5)

        except Exception as e:
            print(f"Error desconocido: {e}. Reintentando en 5 segundos...")
            time.sleep(5)



if __name__ == '__main__':
    # CONECTARSE AL KEEP ALIVE SERVER DE LA BLOCKCHAIN:
    connect_keep_alive_server()

    # CONECTARSE A RABBIT DE BLOCKCHAIN Y EMPEZAR A CONSUMIR:
    threading.Thread(target=main).start()