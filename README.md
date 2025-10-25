# Desktop_Auto_Filer


Main command line:
## This could print where the document will be move to (but not actually moved)
```  python desk_move.py --once --dry-run ``` 

## This is the real clean, which will move the document to the desginated place
```  python desk_move.py --once ``` 

## keep watching Desktop，it will move the new documents once it figured out and move it following the rules
```  python desk_move.py --watch ``` 

## This could undo the most recent move (only undo 1 doc)
```  python desk_move.py --undo ``` 

### Here is the example for terminal testing:

``` 
(base) makinampei@MakiN-MacBook-Pro Desktop_Auto_Filer % python desk_move.py --once --dry-run
[dry-run] Screenshot 2025-09-23 at 21.05.15.png -> /Users/makinampei/Pictures
[dry-run] SF.jpg -> /Users/makinampei/Pictures
[dry-run] Screenshot 2024-06-19 at 14.46.38.png -> /Users/makinampei/Pictures
[dry-run] Screenshot 2024-06-08 at 00.17.59.png -> /Users/makinampei/Pictures
[dry-run] エントリーシート_三菱商事株式会社.pdf -> /Users/makinampei/Documents/PDF
[dry-run] Screenshot 2024-05-24 at 23.49.20.png -> /Users/makinampei/Pictures
[dry-run] Screenshot 2024-07-27 at 16.15.59.png -> /Users/makinampei/Pictures
[dry-run] Screenshot 2024-09-08 at 19.21.16.png -> /Users/makinampei/Pictures
[dry-run] Screenshot 2025-09-23 at 21.04.02.png -> /Users/makinampei/Pictures
[dry-run] Screenshot 2025-02-01 at 20.40.20.png -> /Users/makinampei/Pictures
[dry-run] Screenshot 2025-09-24 at 18.39.41.png -> /Users/makinampei/Pictures
[dry-run] Screenshot 2024-03-21 at 16.24.28.png -> /Users/makinampei/Pictures
[done] moved: 0
``` 

``` 
(base) makinampei@MakiN-MacBook-Pro Desktop_Auto_Filer % python desk_move.py --once
[move] Screenshot 2025-09-23 at 21.05.15.png -> /Users/makinampei/Pictures
[move] SF.jpg -> /Users/makinampei/Pictures
[move] Screenshot 2024-06-19 at 14.46.38.png -> /Users/makinampei/Pictures
[move] Screenshot 2024-06-08 at 00.17.59.png -> /Users/makinampei/Pictures
[move] エントリーシート_三菱商事株式会社.pdf -> /Users/makinampei/Documents/PDF
[move] Screenshot 2024-05-24 at 23.49.20.png -> /Users/makinampei/Pictures
[move] Screenshot 2024-07-27 at 16.15.59.png -> /Users/makinampei/Pictures
[move] Screenshot 2024-09-08 at 19.21.16.png -> /Users/makinampei/Pictures
[move] Screenshot 2025-09-23 at 21.04.02.png -> /Users/makinampei/Pictures
[move] Screenshot 2025-02-01 at 20.40.20.png -> /Users/makinampei/Pictures
[move] Screenshot 2025-09-24 at 18.39.41.png -> /Users/makinampei/Pictures
[move] Screenshot 2024-03-21 at 16.24.28.png -> /Users/makinampei/Pictures
[done] moved: 12
``` 

``` 
(base) makinampei@MakiN-MacBook-Pro Desktop_Auto_Filer % python desk_move.py --undo
[undo] restored to /Users/makinampei/Desktop/Screenshot 2024-03-21 at 16.24.28.png
... (After 12 undos)
(base) makinampei@MakiN-MacBook-Pro Desktop_Auto_Filer % python desk_move.py --undo
[i] nothing to undo
``` 

## In order to make the watchdog work, an package is need to install
``` pip install watchdog ``` 

``` python watch_watchdog.py ``` 
