import os
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
from threading import Thread

# ---------------- ENV ----------------
TOKEN = os.getenv("TOKEN")
API_KEY = os.getenv("SELLAUTH_API_KEY")
SHOP_ID = os.getenv("SELLAUTH_SHOP_ID")

# ---------------- FLASK KEEP ALIVE ----------------
app = Flask("")

@app.route("/")
def home():
    return "Bot Online"

def run_web():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# ---------------- DISCORD SETUP ----------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- SELLAUTH API ----------------
def headers():
    return {"Authorization": f"Bearer {API_KEY}"}

async def api_request(method, url, body=None):
    async with aiohttp.ClientSession() as s:
        async with s.request(method, url, headers=headers(), json=body) as r:
            try:
                js = await r.json(content_type=None)
            except:
                js = None
            return r.status, js

# ---------- INVOICE ----------
async def get_invoice(invoice_id):
    url = f"https://api.sellauth.com/v1/shops/{SHOP_ID}/orders/{invoice_id}"
    status, js = await api_request("GET", url)
    if status != 200 or not js:
        return None
    return js.get("data")

# ---------- ORDER ----------
async def get_order(order_id):
    url = f"https://api.sellauth.com/v1/shops/{SHOP_ID}/orders/{order_id}"
    status, js = await api_request("GET", url)
    return js.get("data") if js else None

# ---------- PRODUCTS ----------
async def list_products():
    url = f"https://api.sellauth.com/v1/shops/{SHOP_ID}/products"
    _, js = await api_request("GET", url)
    return js.get("data", []) if isinstance(js, dict) else []

async def get_variants(pid):
    url = f"https://api.sellauth.com/v1/shops/{SHOP_ID}/products/{pid}"
    _, js = await api_request("GET", url)
    return js.get("data", {}).get("variants", [])

async def append_stock(pid, vid, items):
    url = f"https://api.sellauth.com/v1/shops/{SHOP_ID}/products/{pid}/deliverables/append/{vid}"
    return await api_request("PUT", url, {"deliverables": items})

async def get_stock(pid, vid):
    url = f"https://api.sellauth.com/v1/shops/{SHOP_ID}/products/{pid}/deliverables/{vid}"
    return await api_request("GET", url)

# Quick stock total
async def quick_stock(pid):
    variants = await get_variants(pid)
    total = 0
    for v in variants:
        _, js = await get_stock(pid, v["id"])
        if js and isinstance(js, list):
            total += len(js)
    return total

# ---------------- UI COMPONENTS ----------------
class RestockModal(discord.ui.Modal, title="Restock"):
    stock = discord.ui.TextInput(label="Stock (1 por línea)", style=discord.TextStyle.paragraph)

    def __init__(self, pid, vid):
        super().__init__()
        self.pid = pid
        self.vid = vid

    async def on_submit(self, interaction: discord.Interaction):
        items = [x for x in self.stock.value.splitlines() if x.strip()]
        await append_stock(self.pid, self.vid, items)
        await interaction.response.send_message(f"Added {len(items)} items", ephemeral=True)

class VariantSelect(discord.ui.Select):
    def __init__(self, pid, variants):
        options = [
            discord.SelectOption(label=v["name"], value=str(v["id"]))
            for v in variants
        ]
        super().__init__(placeholder="Select Variant", options=options)
        self.pid = pid

    async def callback(self, interaction: discord.Interaction):
        vid = self.values[0]
        await interaction.response.send_modal(RestockModal(self.pid, vid))

class ProductSelect(discord.ui.Select):
    def __init__(self, products):
        options = [
            discord.SelectOption(label=p["name"], value=str(p["id"]))
            for p in products
        ]
        super().__init__(placeholder="Select Product", options=options)

    async def callback(self, interaction: discord.Interaction):
        pid = self.values[0]
        variants = await get_variants(pid)
        view = discord.ui.View()
        view.add_item(VariantSelect(pid, variants))
        await interaction.response.send_message("Select Variant", view=view, ephemeral=True)

class StockPanel(discord.ui.View):
    @discord.ui.button(label="Restock", style=discord.ButtonStyle.green)
    async def restock(self, interaction: discord.Interaction, button: discord.ui.Button):
        products = await list_products()
        view = discord.ui.View()
        view.add_item(ProductSelect(products))
        await interaction.response.send_message("Select Product", view=view, ephemeral=True)

# ---------------- COMMANDS ----------------
@bot.tree.command(name="invoice", description="Ver invoice por ID")
async def invoice(interaction: discord.Interaction, invoice_id: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("No permiso", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    data = await get_invoice(invoice_id)
    if not data:
        return await interaction.followup.send("Invoice no encontrada")

    embed = discord.Embed(title=f"Invoice {invoice_id}", color=discord.Color.green())
    embed.add_field(name="Email", value=str(data.get("email", "N/A")))
    embed.add_field(name="Precio", value=str(data.get("total_price", "N/A")))
    embed.add_field(name="Estado", value=str(data.get("status", "N/A")))
    embed.add_field(name="Producto", value=str(data.get("product_name", "N/A")))

    deliverables = data.get("deliverables", [])
    if deliverables:
        preview = "\n".join(deliverables[:10])
        embed.add_field(name="Keys / Deliverables", value=f"```{preview}```", inline=False)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="panel-stock", description="Panel de stock")
async def panel_stock(interaction: discord.Interaction):
    await interaction.response.send_message(embed=discord.Embed(title="Stock Panel"), view=StockPanel())

@bot.tree.command(name="product-list", description="Lista productos")
async def product_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    products = await list_products()
    if not products:
        return await interaction.followup.send("No hay productos")
    text = "\n".join([f"{p['name']} - ID: {p['id']}" for p in products])
    await interaction.followup.send(f"```{text}```")

@bot.tree.command(name="stock", description="Ver stock rápido por product ID")
async def stock(interaction: discord.Interaction, product_id: str):
    await interaction.response.defer(ephemeral=True)
    amount = await quick_stock(product_id)
    await interaction.followup.send(f"Stock disponible: {amount}")

@bot.tree.command(name="order", description="Ver pedido por ID")
async def order(interaction: discord.Interaction, order_id: str):
    await interaction.response.defer(ephemeral=True)
    data = await get_order(order_id)
    if not data:
        return await interaction.followup.send("Pedido no encontrado")
    embed = discord.Embed(title=f"Order {order_id}", color=discord.Color.blue())
    embed.add_field(name="Email", value=str(data.get("email", "N/A")))
    embed.add_field(name="Estado", value=str(data.get("status", "N/A")))
    embed.add_field(name="Precio", value=str(data.get("total_price", "N/A")))
    await interaction.followup.send(embed=embed)

# ---------------- READY ----------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot conectado como {bot.user}")

# ---------------- RUN ----------------
keep_alive()
bot.run(TOKEN)
