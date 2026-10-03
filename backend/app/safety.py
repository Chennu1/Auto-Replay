HIGH_RISK_TERMS=['kill myself','suicide','self harm','dox','doxxing','phone number','credit card']
def assess_risk(comment:str)->str:
 t=comment.lower()
 if any(x in t for x in HIGH_RISK_TERMS): return 'high'
 if any(x in t for x in ['threat','scam','fraud','lawsuit']): return 'medium'
 return 'low'
