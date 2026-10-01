"""Prueba manual: clasifica tus correos nuevos UNA vez y muestra el resultado.
Aplica etiquetas 'oficina/...' en Gmail (reversible) y guarda en la base de datos."""
from pipeline import process_new_mail

important = process_new_mail()
print(f"\nCorreos importantes: {len(important)}")
for mail, res in important:
    print(f"- [{res['category']}] {mail['subject']}  ({res['classified_with']})\n    {res['summary']}")
