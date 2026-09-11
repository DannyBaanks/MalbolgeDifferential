# malbolge-differential

**Corre el mismo programa Malbolge en implementaciones independientes y ve exactamente
donde coinciden.**

```console
$ python -m mdiff.diff corpus/hello_world.mb

Malbolge Differential Test

Program: hello_world.mb

  engine:  PASS   (40 steps, 12 bytes out)
  oracle:  PASS   (40 steps, 12 bytes out)
  rust:    PASS   (12 bytes out)

  output:  identical
  halted:  identical
  steps:   identical
  a:       not comparable (fewer than two backends report it)
  c:       not comparable (fewer than two backends report it)
  d:       not comparable (fewer than two backends report it)

RESULT: CONSISTENT
```

**Este repositorio NO contiene ningun interprete de Malbolge.** Apunta a los
que tu tengas construidos y compara lo que hacen. Cada backend corre el programa
el mismo; nada pasa por nada mas.

## Por que

Las implementaciones de Malbolge discrepan de formas que son invisibles hasta que las pones
lado a lado. No en hello-world — en que pasa al EOF, en el estado despues de un
halt, en **como el programa llega a la memoria en primer lugar**.

Ese ultimo resulto ser la parte interesante. Ver
[`findings/D4_loading_is_not_specified.md`](findings/D4_loading_is_not_specified.md):
la semantica que todos citan, Iizawa (2005) Appendix C, es
`void exec( unsigned short *mem )` — recibe la memoria **ya cargada** y
no dice nada sobre como. Entonces cada implementacion decidio por su cuenta, y
decidieron diferente: una llena la cola de la memoria, otra la pone en cero, una
salta whitespace en el fuente y otra no. Programas que pasan de su propia
ultima celda no estan corriendo la misma maquina.

Eso se encontro en la primera comparacion real que corrio este harness, y produjo un
fix en uno de los backends.

## Tres veredictos, no dos

```
CONSISTENT     los backends que pudieron responder, coincidieron
DIVERGENCE     pudieron responder, y discreparon
INCONCLUSIVE   muy pocos pudieron responder para saber
```

El tercero existe porque la mayoria de lo que sale mal en prueba diferencial no es
una diferencia semantica. Un runtime toco su limite de pasos; otro no tiene limite. Uno
se nego a cargar el programa. Un campo no esta disponible en una implementacion.
Reportar cualquiera de eso como divergencia ensena a la gente a ignorar la herramienta.

Dos cosas mas que se niega a hacer:

**Nunca fabrica un campo.** Un interprete que imprime y sale no puede
reportar un conteo de pasos. Eso se registra como no disponible, no como cero, y campos
que menos de dos backends pueden reportar se dejan fuera de la comparacion completamente.

**Separa encoding de semantica.** Un runtime que escribe bytes por un
encoder UTF-8 emite dos bytes donde uno que escribe raw emite uno, para cualquier cosa
≥ 128. Las maquinas coinciden; los flujos no. Eso se reporta como
`kind="encoding"`, aparte de una diferencia real en lo que se imprimo.

## Setup

```sh
cp backends.example.json backends.json     # luego edita las rutas
python -m mdiff.diff corpus/hello_world.mb
```

Se soportan tres tipos de backend, igualando como cada implementacion se expone
a si misma:

| tipo | Para | Reporta |
|---|---|---|
| `engine-ipc` | un interprete que habla JSONL por stdin/stdout | status, steps, output |
| `oracle-python` | un directorio que contiene `oracle.py` | el estado completo de la maquina |
| `rust-cli` | un CLI que toma una ruta de archivo | stdout y terminacion |
| `rustbolge-cli` | [Rustbolge](../Rustbolge) — CLI con limite de steps + reporte JSON | stdout, terminacion, steps, a/c/d finales |

Agregar un cuarto es una funcion en `mdiff/backends.py` que retorna un `Outcome`
y declara que no puede reportar.

## Evidencia

Cada corrida escribe un archivo JSON con el resultado de cada backend, la comparacion, el
hash del programa y las condiciones — porque una divergencia que no puedes reproducir es
una anecdotica. `--no-evidence` lo apaga.

El exit code es `1` solo para `DIVERGENCE`. `INCONCLUSIVE` sale con `0`: es un resultado
normal, no un error.

## Pruebas

```sh
python -m pytest tests/ -v
```

Cubren el comparador, que es donde vive el juicio: que cuenta como
coincidencia cuando un backend no puede reportar un campo, por que un timeout es inconcluso
en vez de divergente, y como se distingue un artefacto UTF-8 de una diferencia
real en la salida.

## Licencia

MIT. Ver [`LICENSE`](LICENSE).

Los interpretes que este harness maneja son proyectos separados con sus propias
licencias y no se incluyen aqui.
