import pika
import json
import hashlib
import random
import requests
import time

def calcular_hash(texto):
    hash = hashlib.md5()
    hash.update(texto.encode('utf-8'))
    return hash.hexdigest()

def post_result(data):
    url = "http://coordinator:5000/solved_task"
    try:
        response = requests.post(url, json=data)
        print("Post response:", response.text)
    except requests.exceptions.RequestException as e:
        print("Failed to send POST request:", e)

def on_message_received(ch, method, properties, body):
    data = json.loads(body)
    print(f"Message {data} received")
    '''
    data = {
        "id": last_id,
        "transactions": transactions, 
        "prefix": prefix,
        "random_num_max": 99999999,
        "last_hash": last_element["hash"] if last_element else ""
    }
    '''

    encontrado = False
    start_time = time.time()
    print("Starting mining process...")
    count = 0
    while not encontrado and count<=data["random_num_max"]:
        number = str(count)
        hash_calculado = calcular_hash(number + str(data['transactions']) + data['last_hash'])
        # number += 1
        '''
        El coordinador valida así (no usa hashlib.sha256()):
        combined_data = f"{number}{transactions}{current_hash}"
        hash_calculado = calcular_hash(combined_data)
        '''
        if hash_calculado.startswith(data['prefix']):
            encontrado = True
            processing_time = time.time() - start_time
            data["processing_time"] = processing_time
            data["hash"] = hash_calculado
            data["number"] = number
        count+=1

    if encontrado:
        post_result(data)
        print(f"Resultado encontrado y posteado para el block con ID {data['id']} en {processing_time:.2f} segundos")
        ch.basic_ack(delivery_tag=method.delivery_tag)
    else:
        print(f"No se encontró un Hash con ese máximo de números")


def main():
    # Configuración de RabbitMQ
    rabbitmq_host = 'rabbitmq'
    rabbitmq_port = 5672
    connected_rabbit = False
    while not connected_rabbit:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbitmq_host, port=rabbitmq_port, credentials=pika.PlainCredentials('guest', 'guest'), heartbeat=0))
            channel = connection.channel()
            channel.exchange_declare(exchange='blockchain_challenge', exchange_type='topic', durable=True)
            result = channel.queue_declare('', exclusive=True)
            queue_name = result.method.queue
            channel.queue_bind(exchange='blockchain_challenge', queue=queue_name, routing_key='tasks')
            connected_rabbit = True
        except Exception as e:
            print(f"Error connectando a RabbitMQ: {e}")
            print("Reintentando en 3 segundos...")
            time.sleep(3)
    
    channel.basic_consume(queue=queue_name, on_message_callback=on_message_received, auto_ack=False)
    print('Waiting for messages. To exit press CTRL+C')
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print("Consumption stopped by user.")
        connection.close()
        print("Connection closed.")

if __name__ == '__main__':
    main()