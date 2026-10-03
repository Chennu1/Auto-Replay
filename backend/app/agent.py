import os,json
from google import genai
from .safety import assess_risk
SYSTEM_PROMPT='''You are Auto-Replay, an AI social comment reply agent. Sound like a real creator, never a customer-service bot. Use comment, content context, creator style and commenter memory. Never invent facts. Keep replies concise. Do not argue with trolls. Return JSON only with intent, sentiment, risk_level, confidence, replies (exactly 3 short candidates), recommended_reply, reason.'''
def _fallback(comment):
 r=assess_risk(comment);t=comment.lower()
 if r!='low':return {'intent':'needs_review','sentiment':'unknown','risk_level':r,'confidence':1.0,'replies':[],'recommended_reply':'','reason':'Safety gate requires human review.'}
 if 'breed' in t:a=['He’s a Shih Tzu ❤️','He’s a Shih Tzu! 😊','He’s our little Shih Tzu 😂']
 elif any(x in t for x in ['cute','adorable','handsome']):a=['He knows it too 😂','Haha, he’ll love this ❤️','He definitely knows he’s cute 😂']
 else:a=['Haha, appreciate it 😄','😂❤️','Glad you enjoyed it!']
 return {'intent':'question' if '?' in t else 'general','sentiment':'positive','risk_level':'low','confidence':0.55,'replies':a,'recommended_reply':a[0],'reason':'Fallback mode; configure GEMINI_API_KEY for contextual generation.'}
def generate_reply(req):
 if not os.getenv('GEMINI_API_KEY'):return _fallback(req.comment)
 r=assess_risk(req.comment)
 if r=='high':return _fallback(req.comment)
 c=genai.Client(api_key=os.getenv('GEMINI_API_KEY'));p=f"{SYSTEM_PROMPT}\nCOMMENT:\n{req.comment}\nCONTENT:\n{req.content_context}\nSTYLE:\n{req.creator_style}\nMEMORY:\n{req.commenter_memory}"
 d=json.loads(c.models.generate_content(model='gemini-2.5-flash',contents=p,config={'response_mime_type':'application/json'}).text);lv={'low':0,'medium':1,'high':2};d['risk_level']=max(d.get('risk_level','low'),r,key=lambda x:lv.get(x,2));return d
