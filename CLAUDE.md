Si tratta di un progetto python per un bot telegram

NOn proporre mai niente di cui non sia sicuro

Rispondi in modo asciutto, senza fronzoli.

Quando fai proposte, fallo in elenchi numerati, in modo che quando rispondo possa citare i punti a cui mi riferisco.

Mantieni aggiornato un file (sviluppi.md) nel quale vai a scrivere ogni volta che concordiamo di fare un commit del progetto, e aggiungi le informazioni specifiche su quanto è stato fatto dall'ultimo commit precedente.

Non cancellare MAI nessun file (chiedi a me e lo farò io).

Aggiungi a .gitignore il file sviluppi.md in modo che non sia committato, e anche il file Istruzio-claude.md

Nella parte iniziale di sviluppi.md verrà conservato l'elenco dei TODO in modo da sapere cosa manca ancora da fare. Mano a mano che le attività previste nel todo vengono effettuate, rimuovile

Ogni volta che viene completata una nuova funzionalità e che viene proposto un commit, proponi e realizza un insieme di test di regressione, e chiedi conferma che tutti i test di regressione precedenti siano ok, in modo da garantire che tutto funzioni correttamente.

QUando ti comunico che sto per committare e pensi ai test, proponimi anche la stringa da inserire su Git per il commit

Se vengono effettuate modifiche al DB da qualche script per cambiarne la struttura, mantieni aggiornato mano a mano un file py che contenga tutte le modifiche in modo da poterlo applicare anche sulla versione di produzione. Il file deve poter essere eseguito anche su un db che contiene già le modifiche senza dare problemi.

