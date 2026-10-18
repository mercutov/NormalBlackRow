# Normal Black Row

Добавляет на картинку тонкую чёрную полоску с одной стороны и пересохраняет файл.

По умолчанию полоска идёт по **левому** краю и имеет ширину **6** пикселей. Холст увеличивается на эту ширину, само изображение не закрашивается.

## Установка

```powershell
py -3 -m pip install -r requirements.txt
```

## Запуск

```powershell
py -3 normal_black_row.py photo.jpg
py -3 normal_black_row.py photo.jpg --side right --width 8
py -3 normal_black_row.py photo.jpg --side top -o photo_bar.jpg
```

Стороны: `left`, `right`, `top`, `bottom` (или `лево`, `право`, `верх`, `низ`).

Без `-o` исходный файл перезаписывается. С `-o` результат пишется в другой путь.
