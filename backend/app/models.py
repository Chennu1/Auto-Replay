from pydantic import BaseModel, Field
class ReplyRequest(BaseModel):
 comment:str=Field(min_length=1,max_length=2000); content_context:str=Field(default='',max_length=6000); creator_style:str=Field(default='casual, short, natural, friendly',max_length=2000); commenter_memory:str=Field(default='',max_length=4000); comment_id:str|None=Field(default=None,max_length=100)
