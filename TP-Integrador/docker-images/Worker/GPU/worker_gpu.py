import os
import pika
import json
import minero_gpu
import requests
import time
import threading

id = -1
coordinador_ip = os.environ.get("COORDINATOR_HOST")
coordinador_puerto = os.environ.get("COORDINATOR_PORT")
keep_alive_server_ip = os.environ.get("KEEPALIVE_HOST")
keep_alive_server_puerto = os.environ.get("KEEPALIVE_PORT")

def post_result(data):
    url = f"http://{coordinador_ip}:{coordinador_puerto}/solved_task"
    try:
        response = requests.post(url, json=data)
        print("POST response:", response.text)
    except requests.exceptions.RequestException as e:
        print("Failed to send POST request:", e)

def minero(ch, method, properties, body):
    data = json.loads(body)
    print(f"Tarea recibida")
    start_time = time.time()
    print("Starting mining process...")
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
        print(f"No se encontró un Hash con ese máximo de números")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # Le indico que no pude, y que no reencole

def send_keep_alive():
    global id
    url = f"http://{keep_alive_server_ip}:{keep_alive_server_puerto}/alive"
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

def main():
    global id
    data = {
        "id": id,
        "type": "gpu"
    }
    url = f"http://{keep_alive_server_ip}:{keep_alive_server_puerto}/alive"
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
    
    # Configuración de RabbitMQ
    user = os.environ.get("RABBITMQ_USER")
    password = os.environ.get("RABBITMQ_PASSWORD")
    rabbitmq_host = os.environ.get("RABBITMQ_HOST")
    rabbitmq_port = os.environ.get("RABBITMQ_PORT")
    connected_rabbit = False
    while not connected_rabbit:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbitmq_host, port=rabbitmq_port, credentials=pika.PlainCredentials(f'{user}', f'{password}'), heartbeat=0))
            channel = connection.channel()
            channel.exchange_declare(exchange='blockchain_challenge', exchange_type='topic', durable=True)
            result = channel.queue_declare('', exclusive=True)
            queue_name = result.method.queue
            channel.queue_bind(exchange='blockchain_challenge', queue=queue_name, routing_key='tasks')
            connected_rabbit = True
            print("Ya se encuentra conectado a RabbitMQ!")
        except Exception as e:
            print(f"Error connectando a RabbitMQ: {e}")
            print("Reintentando en 3 segundos...")
            time.sleep(3)

    channel.basic_consume(queue=queue_name, on_message_callback=minero, auto_ack=False)
    print('Waiting for messages. To exit press CTRL+C')
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print("Consumption stopped by user.")
        connection.close()
        print("Connection closed.")

if __name__ == '__main__':
    main()