"""
Messages routes
"""
from fastapi import APIRouter, HTTPException, Depends, status
from app.database import supabase_admin
from app.middleware.auth import get_current_user
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter(prefix="/messages")


class MessageCreate(BaseModel):
    recipient_id: str
    content: str
    property_id: Optional[str] = None
    application_id: Optional[str] = None


class ConversationCreate(BaseModel):
    property_id: str
    landlord_id: str
    initial_message: str


@router.post("/conversations")
async def create_conversation(
    conversation_data: ConversationCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new conversation (or get existing one) and send initial message
    """
    try:
        tenant_id = current_user["id"]
        
        # Check if conversation already exists
        existing_conv = supabase_admin.table("conversations").select("*").eq(
            "tenant_id", tenant_id
        ).eq("landlord_id", conversation_data.landlord_id).eq(
            "property_id", conversation_data.property_id
        ).execute()
        
        if existing_conv.data:
            conversation_id = existing_conv.data[0]["id"]
        else:
            # Create new conversation
            conv_dict = {
                "tenant_id": tenant_id,
                "landlord_id": conversation_data.landlord_id,
                "property_id": conversation_data.property_id,
                "status": "active"
            }
            
            conv_response = supabase_admin.table("conversations").insert(conv_dict).execute()
            
            if not conv_response.data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to create conversation"
                )
            
            conversation_id = conv_response.data[0]["id"]
        
        # Send initial message
        msg_dict = {
            "conversation_id": conversation_id,
            "sender_id": tenant_id,
            "recipient_id": conversation_data.landlord_id,
            "content": conversation_data.initial_message,
            "property_id": conversation_data.property_id,
            "message_type": "text",
            "read": False
        }
        
        msg_response = supabase_admin.table("messages").insert(msg_dict).execute()
        
        # Update conversation last_message
        supabase_admin.table("conversations").update({
            "last_message": conversation_data.initial_message,
            "last_message_at": datetime.now().isoformat()
        }).eq("id", conversation_id).execute()
        
        return {
            "success": True,
            "conversation_id": conversation_id,
            "message": msg_response.data[0] if msg_response.data else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create conversation: {str(e)}"
        )


@router.get("/conversations")
async def get_conversations(current_user: dict = Depends(get_current_user)):
    """
    Get user's conversations with last message
    """
    try:
        user_id = current_user["id"]
        
        # Fetch conversations (simplified query with error handling)
        try:
            conversations_response = supabase_admin.table("conversations").select(
                "*"
            ).or_(f"tenant_id.eq.{user_id},landlord_id.eq.{user_id}").order("created_at", desc=True).execute()
        except Exception as query_error:
            print(f"Error querying conversations: {str(query_error)}")
            # Return empty list if query fails
            return {
                "success": True,
                "conversations": []
            }
        
        # Return empty list if no conversations
        if not conversations_response.data or len(conversations_response.data) == 0:
            return {
                "success": True,
                "conversations": []
            }
        
        # Format conversations
        conversations = []
        for conv in conversations_response.data:
            try:
                # Fetch property details separately
                property_data = None
                if conv.get("property_id"):
                    property_response = supabase_admin.table("properties").select(
                        "id, title, price, images, location"
                    ).eq("id", conv["property_id"]).execute()
                    if property_response.data:
                        property_data = property_response.data[0]
                
                # Determine conversation partner and fetch their details
                partner_id = None
                if conv.get("tenant_id") == user_id:
                    partner_id = conv.get("landlord_id")
                else:
                    partner_id = conv.get("tenant_id")
                
                # Fetch partner details
                partner = None
                if partner_id:
                    partner_response = supabase_admin.table("users").select(
                        "id, full_name, avatar_url, verification_status"
                    ).eq("id", partner_id).execute()
                    if partner_response.data:
                        partner = partner_response.data[0]
                
                # Count unread messages
                unread_count = 0
                try:
                    unread_response = supabase_admin.table("messages").select("id", count="exact").eq(
                        "conversation_id", conv["id"]
                    ).eq("recipient_id", user_id).eq("read", False).execute()
                    unread_count = unread_response.count if hasattr(unread_response, 'count') else 0
                except:
                    unread_count = 0
                
                conversations.append({
                    "id": conv["id"],
                    "property": property_data,
                    "partner": {
                        "id": partner["id"] if partner else partner_id,
                        "name": partner.get("full_name") if partner else "User",
                        "avatar_url": partner.get("avatar_url") if partner else None,
                        "verified": partner.get("verification_status") == "approved" if partner else False
                    },
                    "last_message": conv.get("last_message"),
                    "last_message_at": conv.get("last_message_at") or conv.get("created_at"),
                    "unread_count": unread_count,
                    "status": conv.get("status", "active")
                })
            except Exception as conv_error:
                # Log error but continue processing other conversations
                print(f"Error processing conversation {conv.get('id')}: {str(conv_error)}")
                continue
        
        return {
            "success": True,
            "conversations": conversations
        }
        
    except Exception as e:
        import traceback
        print(f"Error in get_conversations: {str(e)}")
        print(traceback.format_exc())
        # Return empty list instead of throwing error
        return {
            "success": True,
            "conversations": [],
            "error": str(e)
        }


@router.get("/conversation/{conversation_id}")
async def get_conversation_messages(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get messages in a specific conversation
    """
    try:
        user_id = current_user["id"]
        
        # Verify user is part of conversation
        conv_check = supabase_admin.table("conversations").select("*").eq(
            "id", conversation_id
        ).or_(f"tenant_id.eq.{user_id},landlord_id.eq.{user_id}").execute()
        
        if not conv_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        # Fetch messages (simplified)
        messages_response = supabase_admin.table("messages").select("*").eq(
            "conversation_id", conversation_id
        ).order("timestamp", desc=False).execute()
        
        # Fetch sender details for each message
        messages = []
        for msg in messages_response.data:
            try:
                sender_response = supabase_admin.table("users").select(
                    "id, full_name, avatar_url"
                ).eq("id", msg["sender_id"]).execute()
                
                message_data = {
                    **msg,
                    "sender": sender_response.data[0] if sender_response.data else None
                }
                messages.append(message_data)
            except Exception as msg_error:
                print(f"Error processing message {msg.get('id')}: {str(msg_error)}")
                continue
        
        # Mark messages as read (where current user is recipient)
        supabase_admin.table("messages").update({
            "read": True,
            "read_at": datetime.now().isoformat()
        }).eq("conversation_id", conversation_id).eq("recipient_id", user_id).eq("read", False).execute()
        
        return {
            "success": True,
            "messages": messages
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch messages: {str(e)}"
        )


@router.post("/conversation/{conversation_id}")
async def send_message(
    conversation_id: str,
    message_data: MessageCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Send a message in a conversation
    """
    try:
        sender_id = current_user["id"]
        
        # Verify conversation exists and user is part of it
        conv_check = supabase_admin.table("conversations").select("*").eq(
            "id", conversation_id
        ).or_(f"tenant_id.eq.{sender_id},landlord_id.eq.{sender_id}").execute()
        
        if not conv_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        # Determine recipient
        conv = conv_check.data[0]
        recipient_id = conv["landlord_id"] if conv["tenant_id"] == sender_id else conv["tenant_id"]
        
        # Create message
        msg_dict = {
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "content": message_data.content,
            "property_id": conv["property_id"],
            "message_type": "text",
            "read": False
        }
        
        response = supabase_admin.table("messages").insert(msg_dict).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to send message"
            )
        
        # Update conversation last_message
        supabase_admin.table("conversations").update({
            "last_message": message_data.content,
            "last_message_at": datetime.now().isoformat()
        }).eq("id", conversation_id).execute()
        
        # TODO: Send real-time notification to recipient
        # TODO: Create notification record
        
        return {
            "success": True,
            "message": response.data[0]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to send message: {str(e)}"
        )
