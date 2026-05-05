from google import genai

API_KEY = "AIzaSyC2LX-ihqh_1eGD52BIRbLyzpiAne5syUE"


class NewsAnalyzer:
    def __init__(self, text, date, title= None):
        self.client = genai.Client(api_key=API_KEY)
        self.text = text
        self.date = date
        self.title = title

    def build_prompt(self):
        return f"""
Ты — аналитик новостей и фактчекер.

Твоя задача — проанализировать новость и оценить её достоверность, адекватность и возможные признаки фейка.

ИНСТРУКЦИИ:
1. Если заголовок отсутствует (указано "нет"):
   - Сгенерируй краткий, информативный и нейтральный заголовок на основе текста.
   - Не добавляй кликбейта.

2. Проанализируй новость по следующим критериям:
   - Логичность (есть ли противоречия)
   - Реалистичность (насколько это может быть правдой)
   - Наличие манипуляций (эмоциональные формулировки, давление, кликбейт)
   - Конкретика (есть ли факты, источники, цифры)
   - Подозрительные признаки (слишком громкие заявления, отсутствие деталей и т.д.)

3. Определи:
   - Насколько новость выглядит правдоподобной (в процентах от 0 до 100)
   - Возможный тип: (реальная новость / сомнительная / фейк / мнение)

4. Дай краткий, но содержательный комментарий.

ФОРМАТ ОТВЕТА (строго придерживайся):

Заголовок: ...
Оценка достоверности: ...%
Тип: ...
Проблемы:
- ...
- ...
Комментарий:
...

ДАННЫЕ:

Дата: {self.date}
Заголовок: {self.title if self.title else "нет"}
Текст новости:
{self.text}
"""

    def analyze(self):
        response = self.client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=self.build_prompt()
        )
        return response.text


if __name__ == "__main__":
    analyzer = NewsAnalyzer(
        text="какая-то новость",
        date="какая-то дата",
        title=None
    )

    result = analyzer.analyze()
    print(result)
