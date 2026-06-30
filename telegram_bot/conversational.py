"""
conversational.py — Natural language query handler for Telegram bot.

Inspired by Meridian's conversational interface. Bot can respond to
queries like "why did you skip?", "show me your losses", etc.
"""
import logging
from typing import Optional

from core.decision_log import get_decision_log

logger = logging.getLogger("conversational")


class ConversationalHandler:
    """
    Handle natural language queries about trading decisions.
    
    Pattern matching for common queries, with structured responses
    from decision log.
    """
    
    def __init__(self):
        self.decision_log = get_decision_log()
    
    async def handle(self, message: str, user_id: Optional[int] = None) -> str:
        """
        Route message to appropriate handler.
        
        Args:
            message: User's text message
            user_id: Telegram user ID (for permission checks)
        
        Returns:
            Response text (Markdown formatted)
        """
        msg_lower = message.lower().strip()
        
        # Pattern: "why skip" / "why did you skip" / "kenapa skip"
        if any(word in msg_lower for word in ["why", "kenapa", "mengapa"]) and \
           any(word in msg_lower for word in ["skip", "pass", "lewat"]):
            return await self.explain_last_skip()
        
        # Pattern: "why up" / "why bullish" / "kenapa up"
        elif any(word in msg_lower for word in ["why", "kenapa"]) and \
             any(word in msg_lower for word in ["up", "bullish", "long"]):
            return await self.explain_last_up()
        
        # Pattern: "why down" / "why bearish" / "kenapa down"
        elif any(word in msg_lower for word in ["why", "kenapa"]) and \
             any(word in msg_lower for word in ["down", "bearish", "short"]):
            return await self.explain_last_down()
        
        # Pattern: "show mistakes" / "show losses" / "tampilkan loss"
        elif any(word in msg_lower for word in ["mistake", "loss", "kalah", "rugi"]):
            return await self.show_losses()
        
        # Pattern: "show wins" / "profit" / "untung"
        elif any(word in msg_lower for word in ["win", "profit", "untung", "menang"]):
            return await self.show_wins()
        
        # Pattern: "last decision" / "recent" / "terakhir"
        elif any(word in msg_lower for word in ["last", "recent", "terakhir", "terbaru"]):
            return await self.show_recent()
        
        # Pattern: "summary" / "ringkasan"
        elif any(word in msg_lower for word in ["summary", "ringkasan", "overview"]):
            return await self.show_summary()
        
        # Pattern: "help" / "commands" / "bantuan"
        elif any(word in msg_lower for word in ["help", "bantuan", "command"]):
            return self.show_help()
        
        else:
            return self.not_understood(message)
    
    async def explain_last_skip(self) -> str:
        """Explain why the last SKIP decision was made."""
        skips = self.decision_log.get_by_type("skip", limit=1)
        
        if not skips:
            return "🤷 Belum ada SKIP decision dalam history."
        
        last = skips[0]
        
        response = f"**Why SKIP? (Last cycle)**\n\n"
        response += f"📅 **Time:** {last['timestamp'][:19].replace('T', ' ')}\n"
        response += f"🔖 **Cycle:** `{last['cycle_id']}`\n\n"
        response += f"**Summary:**\n{last['summary']}\n\n"
        response += f"**Reason:**\n{last['reason']}\n"
        
        if last.get('risks'):
            response += f"\n**Risks if traded:**\n"
            for risk in last['risks']:
                response += f"  • {risk}\n"
        
        if last.get('rejected'):
            response += f"\n**Alternatives rejected:**\n"
            for alt in last['rejected']:
                response += f"  • {alt}\n"
        
        return response
    
    async def explain_last_up(self) -> str:
        """Explain why the last UP decision was made."""
        ups = self.decision_log.get_by_type("up", limit=1) + \
              self.decision_log.get_by_type("lean_up", limit=1)
        
        if not ups:
            return "🤷 Belum ada UP decision dalam history recent."
        
        last = sorted(ups, key=lambda x: x['timestamp'], reverse=True)[0]
        
        response = f"**Why UP? (Last trade)**\n\n"
        response += f"📅 **Time:** {last['timestamp'][:19].replace('T', ' ')}\n"
        response += f"🔖 **Cycle:** `{last['cycle_id']}`\n"
        response += f"📊 **Type:** {last['type'].upper().replace('_', ' ')}\n\n"
        response += f"**Summary:**\n{last['summary']}\n\n"
        response += f"**Reason:**\n{last['reason']}\n"
        
        metrics = last.get('metrics', {})
        if metrics:
            response += f"\n**Metrics:**\n"
            if metrics.get('confidence'):
                response += f"  • Confidence: {metrics['confidence']}/10\n"
            if metrics.get('position_size_usd'):
                response += f"  • Position: ${metrics['position_size_usd']:.2f}\n"
            if metrics.get('expected_value'):
                response += f"  • EV: {metrics['expected_value']:.4f}\n"
        
        if last.get('risks'):
            response += f"\n**Risks considered:**\n"
            for risk in last['risks']:
                response += f"  • {risk}\n"
        
        return response
    
    async def explain_last_down(self) -> str:
        """Explain why the last DOWN decision was made."""
        downs = self.decision_log.get_by_type("down", limit=1) + \
                self.decision_log.get_by_type("lean_down", limit=1)
        
        if not downs:
            return "🤷 Belum ada DOWN decision dalam history recent."
        
        last = sorted(downs, key=lambda x: x['timestamp'], reverse=True)[0]
        
        response = f"**Why DOWN? (Last trade)**\n\n"
        response += f"📅 **Time:** {last['timestamp'][:19].replace('T', ' ')}\n"
        response += f"🔖 **Cycle:** `{last['cycle_id']}`\n"
        response += f"📊 **Type:** {last['type'].upper().replace('_', ' ')}\n\n"
        response += f"**Summary:**\n{last['summary']}\n\n"
        response += f"**Reason:**\n{last['reason']}\n"
        
        metrics = last.get('metrics', {})
        if metrics:
            response += f"\n**Metrics:**\n"
            if metrics.get('confidence'):
                response += f"  • Confidence: {metrics['confidence']}/10\n"
            if metrics.get('position_size_usd'):
                response += f"  • Position: ${metrics['position_size_usd']:.2f}\n"
        
        return response
    
    async def show_losses(self) -> str:
        """Show recent losing trades."""
        # TODO: Requires outcome tracking (Phase 4)
        return ("📊 **Losses tracking coming soon!**\n\n"
                "This feature requires outcome tracking (Phase 4: Self-Correction).\n"
                "Once we track actual outcomes (5min later), losses will be available here.\n\n"
                "For now, use `/history` to see all decisions.")
    
    async def show_wins(self) -> str:
        """Show recent winning trades."""
        # TODO: Requires outcome tracking (Phase 4)
        return ("🎯 **Wins tracking coming soon!**\n\n"
                "This feature requires outcome tracking (Phase 4: Self-Correction).\n"
                "Once we track actual outcomes (5min later), wins will be available here.\n\n"
                "For now, use `/history` to see all decisions.")
    
    async def show_recent(self) -> str:
        """Show recent decisions."""
        recent = self.decision_log.get_recent(limit=5)
        
        if not recent:
            return "📝 Belum ada decision history."
        
        response = f"**Recent Decisions (last {len(recent)}):**\n\n"
        
        for i, d in enumerate(recent, 1):
            decision_type = d['type'].upper().replace('_', ' ')
            emoji = "🟢" if d['type'] in ['up', 'lean_up'] else \
                    "🔴" if d['type'] in ['down', 'lean_down'] else "⚪"
            
            response += f"{i}. {emoji} **{decision_type}**\n"
            response += f"   {d['timestamp'][:16].replace('T', ' ')} | `{d['cycle_id']}`\n"
            response += f"   {d['summary']}\n"
            
            if d.get('metrics', {}).get('confidence'):
                response += f"   Confidence: {d['metrics']['confidence']}/10\n"
            
            response += "\n"
        
        return response
    
    async def show_summary(self) -> str:
        """Show summary statistics."""
        recent = self.decision_log.get_recent(limit=20)
        
        if not recent:
            return "📊 Belum ada data untuk summary."
        
        # Count by type
        skips = sum(1 for d in recent if d['type'] == 'skip')
        ups = sum(1 for d in recent if d['type'] in ['up', 'lean_up'])
        downs = sum(1 for d in recent if d['type'] in ['down', 'lean_down'])
        
        response = f"**Decision Summary (last {len(recent)} cycles):**\n\n"
        response += f"⚪ **SKIP:** {skips} ({skips/len(recent)*100:.1f}%)\n"
        response += f"🟢 **UP/LEAN_UP:** {ups} ({ups/len(recent)*100:.1f}%)\n"
        response += f"🔴 **DOWN/LEAN_DOWN:** {downs} ({downs/len(recent)*100:.1f}%)\n\n"
        
        # Most recent
        last = recent[0]
        response += f"**Last decision:**\n"
        response += f"{last['type'].upper()} | {last['summary']}\n"
        response += f"{last['timestamp'][:16].replace('T', ' ')}\n"
        
        return response
    
    def show_help(self) -> str:
        """Show available conversational queries."""
        return """**💬 Conversational Queries**

You can ask me naturally in English or Indonesian:

**About decisions:**
• "why skip?" / "kenapa skip?"
• "why up?" / "kenapa up?"
• "why down?" / "kenapa down?"
• "show recent" / "tampilkan terakhir"

**Analysis (coming soon):**
• "show mistakes" / "tampilkan loss"
• "show wins" / "tampilkan profit"
• "what did you learn?" / "apa yang dipelajari?"

**General:**
• "summary" / "ringkasan"
• "help" / "bantuan"

**Commands:** Use /help for full command list.
"""
    
    def not_understood(self, message: str) -> str:
        """Fallback when query not recognized."""
        return (f"🤔 Sorry, saya belum paham query: \"{message[:50]}\"\n\n"
                f"Try:\n"
                f"• \"why skip?\"\n"
                f"• \"show recent\"\n"
                f"• \"summary\"\n"
                f"• \"help\" untuk list lengkap")


# Global instance
_handler: Optional[ConversationalHandler] = None


def get_conversational_handler() -> ConversationalHandler:
    """Get or create global ConversationalHandler instance."""
    global _handler
    if _handler is None:
        _handler = ConversationalHandler()
    return _handler


async def handle_message(message: str, user_id: Optional[int] = None) -> str:
    """Convenience function to handle conversational message."""
    return await get_conversational_handler().handle(message, user_id)
