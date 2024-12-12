from google.cloud import compute_v1
from google.oauth2 import service_account
import os

PROJECT_ID = "integrador-sdypp"
ZONE = 'us-central1-b'
CREDENTIALS_PATH = os.environ.get("CREDENTIALS_PATH")
rabbitmq_host = os.environ.get("RABBITMQ_HOST")
rabbitmq_port = os.environ.get("RABBITMQ_PORT")

def crear_instancias(cantidad):
    credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_PATH)

    # Configuración de la instancia
    INSTANCE_NAME_PREFIX = 'workercpu'
    MACHINE_TYPE = f'zones/{ZONE}/machineTypes/e2-small' 
    SUBNETWORK = f'projects/{PROJECT_ID}/regions/us-central1/subnetworks/default'
    SOURCE_IMAGE = f'projects/{PROJECT_ID}/global/images/packer-1733515674' 
    NETWORK_INTERFACE = {
        'subnetwork': SUBNETWORK,
        'access_configs': [
            {
                'name': 'External NAT'
            }
        ]
    }

    compute_client = compute_v1.InstancesClient(credentials=credentials)

    for i in range(cantidad):
        instance_name = f"{INSTANCE_NAME_PREFIX}{i+1}"
        config = {
            'name': instance_name,
            'machine_type': MACHINE_TYPE,
            'disks': [
                {
                    'boot': True,
                    'auto_delete': True,
                    'initialize_params': {
                        'source_image': SOURCE_IMAGE,
                    }
                }
            ],
            'network_interfaces': [NETWORK_INTERFACE],
            'metadata': {
                'items': [
                    {
                        'key': 'startup-script',
                        'value': f"""#!/bin/bash
                        sudo docker run -d -p 5000:5000 \
                        --name worker-cpu \
                        -e RABBITMQ_HOST={rabbitmq_host} \
                        -e RABBITMQ_PORT={rabbitmq_port} \
                        grupo4sdypp/tp-integrador-cpu-worker:1.0.0"""
                        
                    }
                ]
            }
        }

        print(f"Creating instance {instance_name}...")
        
        # Crear la instancia
        operation = compute_client.insert(
            project=PROJECT_ID,
            zone=ZONE,
            instance_resource=config
        )

        # Esperar la operación
        operation.result()  # Esto bloqueará hasta que la instancia se haya creado

        print(f"Instance {instance_name} created successfully!")

    print(f"All instances created successfully.")

def destruir_instancias():
    credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_PATH)

    compute_client = compute_v1.InstancesClient(credentials=credentials)

    # Listar todas las instancias en la zona especificada
    instance_list = compute_client.list(project=PROJECT_ID, zone=ZONE)

    # Iterar sobre las instancias y eliminarlas una por una
    for instance in instance_list:
        instance_name = instance.name
        print(f"Deleting instance {instance_name}...")

        # Eliminar la instancia
        compute_client.delete(
            project=PROJECT_ID, zone=ZONE, instance=instance_name
        )

    print("All instances have been destroyed.")

# Llamadas de ejemplo:
# Crear 5 instancias
crear_instancias(2)
