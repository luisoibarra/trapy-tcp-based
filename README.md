# Trapy

> Luis Ernesto Ibarra Vázquez (luis.ibarra@estudiantes.matcom.uh.cu)

## Descripción

En el proyecto se implementa una virtualización de la capa de transporte basada en TCP  

## Implementa

    - Demltiplexing
    - Verificación de paquetes corruptos
    - Control del tiempo de espera en el envío de los paquetes
    - Control de Flujo
    - Control de Congestión (Slow Start)

## Usos

Importar las funciones siguientes y usarlas como les sea necesario
```python
from trapy.trapy import listen, accept, dial, send, recv, close
```

Para el correcto uso de la aplicación es necesario tener **una** instancia de la clase TCP activa **por proceso**.
```python
from trapy.trapy import TCP

tcp_virtual_layer = TCP() # Mantener una sola instancia de la clase corriendo por proceso
```  

Para ejemplos básicos de su uso puede referirse a *usage.py*

## Test y pruebas

Puede probar la transferencia de archivos y su uso entre procesos usando el módulo *serve_file*
con los siguientes comandos:  

Para crear los archivos a copiar:

```bash
./mycreate_data.sh
```

Para correr el server:

```bash
sudo python3 -m serve_file --accept 127.0.0.1:6500 --file mytests/data/large.txt --chunk-size 65000
```

Para correr el cliente:

```bash
sudo python3 -m serve_file --dial 127.0.0.1:6500 --file mytests/tmp-data/large.txt --chunk-size 65000
```

Para correr los unittest:

```bash
sudo python3 -m unittest discover mytests
```

## Otros usos

Para probar diferentes escenarios puede en los que se simule perdida de paquete, reordenamiento de estos, entre otros puede sobreescribir el método *_can_queue_data* de *TCP*.
