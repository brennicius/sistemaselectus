# -*- coding: utf-8 -*-
"""Módulo Financeiro — contas a pagar/receber, NF-e (XML), plano de contas,
fluxo de caixa e DRE. Registrado no app principal via init_app(app, get_db)."""
import io, re, zipfile, functools
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, abort)
from werkzeug.security import generate_password_hash, check_password_hash

bp = Blueprint('fin', __name__, url_prefix='/financeiro')
_get_db = None

PERMISSOES = [
    ('perm_baixar',  'Registrar pagamentos e recebimentos'),
    ('perm_fluxo',   'Ver saldos, fluxo de caixa e DRE'),
    ('perm_excluir', 'Cancelar e excluir lançamentos'),
]
FORMAS_PGTO = ['Boleto', 'PIX', 'Transferência', 'Cartão de crédito', 'Cartão de débito',
               'Dinheiro', 'Débito automático', 'Cheque', 'Outro']
MODELOS = ['NF-e', 'NFC-e', 'NFS-e', 'Boleto', 'Recibo', 'Fatura', 'Folha', 'Imposto', 'Outro']
TPAG = {'01': 'Dinheiro', '02': 'Cheque', '03': 'Cartão de crédito', '04': 'Cartão de débito',
        '05': 'Outro', '10': 'Outro', '11': 'Outro', '12': 'Outro', '13': 'Outro',
        '15': 'Boleto', '16': 'Transferência', '17': 'PIX', '18': 'Transferência', '90': 'Outro', '99': 'Outro'}

# ─────────────────────────── Plano de contas padrão ─────────────────────────
# (código, nome, tipo R/D) — grupos são as contas que têm filhas
PLANO_PADRAO = [
    ('1', 'RECEITAS', 'R'),
    ('1.1', 'Receita Operacional', 'R'),
    ('1.1.01', 'Venda de Mercadorias (PDVs)', 'R'),
    ('1.1.02', 'Venda de Refeições e Marmitas', 'R'),
    ('1.1.03', 'Contratos (Hospitais e Empresas)', 'R'),
    ('1.1.04', 'Serviços (Concierge)', 'R'),
    ('1.1.05', 'Venda de Café (máquinas)', 'R'),
    ('1.2', 'Receitas Financeiras', 'R'),
    ('1.2.01', 'Rendimentos de Aplicações', 'R'),
    ('1.2.02', 'Juros e Descontos Obtidos', 'R'),
    ('1.3', 'Outras Receitas', 'R'),
    ('1.3.01', 'Outras Receitas Operacionais', 'R'),
    ('2', 'DEDUÇÕES DA RECEITA', 'D'),
    ('2.1', 'Impostos e Deduções', 'D'),
    ('2.1.01', 'Simples Nacional / Impostos sobre Vendas', 'D'),
    ('2.1.02', 'Taxas de Cartão e Maquininhas', 'D'),
    ('2.1.03', 'Devoluções e Cancelamentos', 'D'),
    ('2.1.04', 'Repasses e Comissões sobre Vendas', 'D'),
    ('3', 'CUSTOS (CMV)', 'D'),
    ('3.1', 'Insumos e Mercadorias', 'D'),
    ('3.1.01', 'Hortifruti', 'D'),
    ('3.1.02', 'Carnes, Aves e Peixes', 'D'),
    ('3.1.03', 'Mercearia', 'D'),
    ('3.1.04', 'Laticínios e Frios', 'D'),
    ('3.1.05', 'Padaria e Confeitaria', 'D'),
    ('3.1.06', 'Bebidas e Mercadorias para Revenda', 'D'),
    ('3.1.07', 'Embalagens e Descartáveis', 'D'),
    ('3.1.08', 'Café e Insumos de Café', 'D'),
    ('3.1.09', 'Gás de Cozinha', 'D'),
    ('3.1.10', 'Fretes sobre Compras', 'D'),
    ('4', 'DESPESAS OPERACIONAIS', 'D'),
    ('4.1', 'Pessoal', 'D'),
    ('4.1.01', 'Salários', 'D'),
    ('4.1.02', 'Encargos (INSS, FGTS)', 'D'),
    ('4.1.03', 'Vale-Transporte', 'D'),
    ('4.1.04', 'Vale-Alimentação / Refeição', 'D'),
    ('4.1.05', 'Férias e 13º Salário', 'D'),
    ('4.1.06', 'Rescisões', 'D'),
    ('4.1.07', 'Pró-labore', 'D'),
    ('4.1.08', 'Uniformes e EPIs', 'D'),
    ('4.1.09', 'Exames e Saúde Ocupacional', 'D'),
    ('4.2', 'Ocupação', 'D'),
    ('4.2.01', 'Aluguel', 'D'),
    ('4.2.02', 'Condomínio', 'D'),
    ('4.2.03', 'Energia Elétrica', 'D'),
    ('4.2.04', 'Água e Esgoto', 'D'),
    ('4.2.05', 'Internet e Telefone', 'D'),
    ('4.2.06', 'IPTU e Taxas do Imóvel', 'D'),
    ('4.2.07', 'Manutenção Predial', 'D'),
    ('4.3', 'Administrativas', 'D'),
    ('4.3.01', 'Contabilidade', 'D'),
    ('4.3.02', 'Sistemas e Software', 'D'),
    ('4.3.03', 'Material de Escritório', 'D'),
    ('4.3.04', 'Material de Limpeza e Higiene', 'D'),
    ('4.3.05', 'Taxas, Licenças e Alvarás', 'D'),
    ('4.3.06', 'Consultorias e Honorários', 'D'),
    ('4.3.07', 'Controle de Pragas e Análises', 'D'),
    ('4.4', 'Comerciais e Logística', 'D'),
    ('4.4.01', 'Marketing e Publicidade', 'D'),
    ('4.4.02', 'Fretes e Entregas', 'D'),
    ('4.4.03', 'Combustível e Veículos', 'D'),
    ('4.5', 'Manutenção', 'D'),
    ('4.5.01', 'Manutenção de Equipamentos', 'D'),
    ('4.5.02', 'Manutenção das Máquinas de Café', 'D'),
    ('5', 'RESULTADO FINANCEIRO', 'D'),
    ('5.1', 'Despesas Financeiras', 'D'),
    ('5.1.01', 'Tarifas Bancárias', 'D'),
    ('5.1.02', 'Juros e Multas Pagos', 'D'),
    ('5.1.03', 'IOF', 'D'),
    ('6', 'INVESTIMENTOS', 'D'),
    ('6.1', 'Imobilizado', 'D'),
    ('6.1.01', 'Máquinas e Equipamentos', 'D'),
    ('6.1.02', 'Móveis e Utensílios', 'D'),
    ('6.1.03', 'Obras e Reformas', 'D'),
    ('7', 'MOVIMENTAÇÕES NÃO OPERACIONAIS', 'D'),
    ('7.1', 'Entradas não operacionais', 'R'),
    ('7.1.01', 'Empréstimos Recebidos', 'R'),
    ('7.1.02', 'Aporte de Sócios', 'R'),
    ('7.2', 'Saídas não operacionais', 'D'),
    ('7.2.01', 'Pagamento de Empréstimos', 'D'),
    ('7.2.02', 'Distribuição de Lucros', 'D'),
]


def _db():
    return _get_db()


def init_tables():
    db = _db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS fin_config (
            chave TEXT PRIMARY KEY, valor TEXT);
        CREATE TABLE IF NOT EXISTS fin_usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            login TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            perfil TEXT NOT NULL DEFAULT 'usuario' CHECK(perfil IN ('master','usuario')),
            perm_baixar INTEGER NOT NULL DEFAULT 0,
            perm_fluxo INTEGER NOT NULL DEFAULT 0,
            perm_excluir INTEGER NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS fin_contas_bancarias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'banco',
            banco TEXT, agencia TEXT, conta TEXT,
            saldo_inicial REAL NOT NULL DEFAULT 0,
            data_saldo_inicial TEXT,
            ativo INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS fin_plano_contas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('R','D')),
            ativo INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS fin_pessoas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cnpj_cpf TEXT,
            tipo TEXT NOT NULL DEFAULT 'F',
            plano_conta_id INTEGER REFERENCES fin_plano_contas(id),
            ativo INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS fin_documentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            natureza TEXT NOT NULL CHECK(natureza IN ('pagar','receber')),
            origem TEXT NOT NULL DEFAULT 'manual',
            modelo TEXT,
            numero TEXT, serie TEXT, chave TEXT,
            pessoa_id INTEGER REFERENCES fin_pessoas(id),
            data_emissao TEXT,
            data_competencia TEXT,
            valor_total REAL NOT NULL DEFAULT 0,
            plano_conta_id INTEGER REFERENCES fin_plano_contas(id),
            descricao TEXT,
            nf_entrada_id INTEGER,
            cancelado INTEGER NOT NULL DEFAULT 0,
            xml TEXT,
            criado_por TEXT,
            criado_em TEXT DEFAULT (datetime('now','localtime')));
        CREATE UNIQUE INDEX IF NOT EXISTS ux_fin_doc_chave
            ON fin_documentos(chave) WHERE chave IS NOT NULL AND chave <> '';
        CREATE TABLE IF NOT EXISTS fin_parcelas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            documento_id INTEGER NOT NULL REFERENCES fin_documentos(id) ON DELETE CASCADE,
            numero TEXT,
            vencimento TEXT,
            valor REAL NOT NULL,
            forma_pagamento TEXT,
            conta_bancaria_id INTEGER REFERENCES fin_contas_bancarias(id),
            data_pagamento TEXT,
            valor_pago REAL,
            juros REAL DEFAULT 0,
            desconto REAL DEFAULT 0,
            obs TEXT,
            baixado_por TEXT,
            baixado_em TEXT);
        CREATE INDEX IF NOT EXISTS ix_fin_parc_venc ON fin_parcelas(vencimento);
        CREATE INDEX IF NOT EXISTS ix_fin_parc_pgto ON fin_parcelas(data_pagamento);
        CREATE TABLE IF NOT EXISTS fin_transferencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            origem_id INTEGER NOT NULL REFERENCES fin_contas_bancarias(id),
            destino_id INTEGER NOT NULL REFERENCES fin_contas_bancarias(id),
            valor REAL NOT NULL,
            obs TEXT,
            criado_por TEXT);
        CREATE TABLE IF NOT EXISTS fin_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT, acao TEXT, detalhe TEXT,
            em TEXT DEFAULT (datetime('now','localtime')));
    ''')
    try:
        db.execute('ALTER TABLE nf_entradas ADD COLUMN chave TEXT')
    except Exception:
        pass
    if db.execute('SELECT COUNT(*) FROM fin_plano_contas').fetchone()[0] == 0:
        db.executemany('INSERT INTO fin_plano_contas (codigo, nome, tipo) VALUES (?,?,?)', PLANO_PADRAO)
    db.commit(); db.close()


# ─────────────────────────────── Utilidades ─────────────────────────────────
def _num(v, default=0.0):
    if v is None:
        return default
    s = str(v).strip().replace('R$', '').replace(' ', '')
    if not s:
        return default
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return default


def _digits(s):
    return re.sub(r'\D', '', s or '')


def _hoje():
    return date.today().isoformat()


def _cfg(db, chave, default=''):
    r = db.execute('SELECT valor FROM fin_config WHERE chave=?', (chave,)).fetchone()
    return r['valor'] if r and r['valor'] is not None else default


def _set_cfg(db, chave, valor):
    db.execute('INSERT INTO fin_config (chave, valor) VALUES (?,?) '
               'ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor', (chave, valor))


def _user():
    uid = session.get('fin_uid')
    if not uid:
        return None
    db = _db()
    u = db.execute('SELECT * FROM fin_usuarios WHERE id=? AND ativo=1', (uid,)).fetchone()
    db.close()
    return u


def _pode(u, perm):
    if not u:
        return False
    if u['perfil'] == 'master':
        return True
    if perm == 'master':
        return False
    return bool(u[perm]) if perm else True


def requer(perm=None):
    """perm: None (qualquer usuário logado), 'master', ou uma chave de PERMISSOES."""
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a, **kw):
            u = _user()
            if not u:
                return redirect(url_for('fin.login', next=request.path))
            if not _pode(u, perm):
                flash('Seu usuário não tem acesso a esta função.', 'warning')
                return redirect(url_for('fin.painel'))
            request.fin_user = u
            return fn(*a, **kw)
        return wrap
    return deco


def _log(db, acao, detalhe=''):
    u = getattr(request, 'fin_user', None)
    db.execute('INSERT INTO fin_log (usuario, acao, detalhe) VALUES (?,?,?)',
               (u['login'] if u else None, acao, detalhe))


def _plano_analiticas(db, tipo=None):
    """Contas que aceitam lançamento (as que não têm filhas)."""
    rows = db.execute('SELECT * FROM fin_plano_contas WHERE ativo=1 ORDER BY codigo').fetchall()
    codigos = [r['codigo'] for r in rows]
    out = []
    for r in rows:
        if any(c.startswith(r['codigo'] + '.') for c in codigos):
            continue
        if tipo and r['tipo'] != tipo:
            continue
        out.append(r)
    return out


def _pessoa(db, nome, doc, tipo):
    doc = _digits(doc)
    row = None
    if doc:
        row = db.execute('SELECT * FROM fin_pessoas WHERE cnpj_cpf=?', (doc,)).fetchone()
    if not row and nome:
        row = db.execute('SELECT * FROM fin_pessoas WHERE UPPER(nome)=UPPER(?)', (nome.strip(),)).fetchone()
    if row:
        if row['tipo'] != tipo and row['tipo'] != 'A':
            db.execute("UPDATE fin_pessoas SET tipo='A' WHERE id=?", (row['id'],))
        return row['id'], row['plano_conta_id']
    cur = db.execute('INSERT INTO fin_pessoas (nome, cnpj_cpf, tipo) VALUES (?,?,?)',
                     ((nome or 'Sem nome').strip(), doc or None, tipo))
    return cur.lastrowid, None


def _status_parcela(p, hoje=None):
    hoje = hoje or _hoje()
    if p['data_pagamento']:
        return 'pago'
    if p['vencimento'] and p['vencimento'] < hoje:
        return 'atrasado'
    return 'aberto'


# ───────────────────────────── Leitura de NF-e ──────────────────────────────
def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and '}' in el.tag:
            el.tag = el.tag.split('}', 1)[1]
    return root


def _t(el, path, default=''):
    if el is None:
        return default
    f = el.find(path)
    return f.text.strip() if f is not None and f.text else default


def parse_nfe_xml(data):
    """Retorna dict com tipo 'nfe' ou 'cancelamento', ou levanta ValueError."""
    try:
        root = _strip_ns(ET.fromstring(data))
    except ET.ParseError as e:
        raise ValueError(f'XML inválido ({e})')
    # Evento de cancelamento
    ev = root if root.tag == 'evento' else root.find('.//evento')
    if root.tag in ('procEventoNFe', 'evento') or (ev is not None and root.find('.//infNFe') is None):
        inf = root.find('.//infEvento')
        if inf is not None and _t(inf, 'tpEvento') == '110111':
            return {'tipo': 'cancelamento', 'chave': _t(inf, 'chNFe')}
        raise ValueError('Evento que não é cancelamento — ignorado')
    inf = root.find('.//infNFe')
    if inf is None:
        raise ValueError('Não é um XML de NF-e/NFC-e')
    chave = (inf.get('Id') or '').replace('NFe', '')
    ide, emit, dest = inf.find('ide'), inf.find('emit'), inf.find('dest')
    dh = _t(ide, 'dhEmi') or _t(ide, 'dEmi')
    tot = inf.find('total/ICMSTot')
    itens = []
    for det in inf.findall('det'):
        p = det.find('prod')
        itens.append({
            'codigo': _t(p, 'cProd'), 'descricao': _t(p, 'xProd'),
            'ncm': _t(p, 'NCM'), 'cfop': _t(p, 'CFOP'), 'unid': _t(p, 'uCom'),
            'qtd': float(_t(p, 'qCom') or 0),
            'vunit': float(_t(p, 'vUnCom') or 0), 'total': float(_t(p, 'vProd') or 0),
        })
    dups = [{'numero': _t(d, 'nDup'), 'vencimento': _t(d, 'dVenc')[:10],
             'valor': float(_t(d, 'vDup') or 0)} for d in inf.findall('cobr/dup')]
    pags = [{'forma': TPAG.get(_t(d, 'tPag'), 'Outro'), 'valor': float(_t(d, 'vPag') or 0)}
            for d in inf.findall('pag/detPag')]
    return {
        'tipo': 'nfe', 'chave': chave,
        'modelo': 'NFC-e' if _t(ide, 'mod') == '65' else 'NF-e',
        'numero': _t(ide, 'nNF'), 'serie': _t(ide, 'serie'),
        'data_emissao': dh[:10],
        'emit_cnpj': _t(emit, 'CNPJ') or _t(emit, 'CPF'), 'emit_nome': _t(emit, 'xNome'),
        'dest_cnpj': _t(dest, 'CNPJ') or _t(dest, 'CPF'), 'dest_nome': _t(dest, 'xNome'),
        'total': float(_t(tot, 'vNF') or 0),
        'itens': itens, 'dups': dups, 'pags': pags,
        'natureza_op': _t(ide, 'natOp'),
    }


def _arquivos_xml(files):
    """Gera (nome, bytes) a partir de uploads .xml e .zip."""
    for f in files:
        nome = (f.filename or '').lower()
        data = f.read()
        if nome.endswith('.zip'):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for n in z.namelist():
                        if n.lower().endswith('.xml'):
                            yield n, z.read(n)
            except zipfile.BadZipFile:
                yield f.filename, None
        elif nome.endswith('.xml'):
            yield f.filename, data


def _sugerir_insumo(db, cnpj, descricao):
    r = db.execute('''SELECT ni.insumo_id FROM nf_itens ni JOIN nf_entradas ne ON ne.id = ni.nf_id
                      WHERE ni.insumo_id IS NOT NULL AND UPPER(ni.descricao_nf)=UPPER(?)
                      ORDER BY (ne.cnpj = ?) DESC, ni.id DESC LIMIT 1''',
                   (descricao, cnpj)).fetchone()
    if r:
        return r['insumo_id']
    r = db.execute('SELECT id FROM insumos WHERE UPPER(nome)=UPPER(?)', (descricao,)).fetchone()
    return r['id'] if r else None


def _criar_nf_entrada(db, nf):
    """Cria a NF na tela Entrada NF (estoque) para confirmação dos itens."""
    ex = db.execute('SELECT id FROM nf_entradas WHERE chave=? OR (numero=? AND serie=? AND cnpj=?)',
                    (nf['chave'], nf['numero'], nf['serie'], _digits(nf['emit_cnpj']))).fetchone()
    if ex:
        return ex['id'], False
    cur = db.execute('''INSERT INTO nf_entradas (numero, serie, fornecedor, cnpj, data_emissao, total, status, chave)
                        VALUES (?,?,?,?,?,?, 'pendente', ?)''',
                     (nf['numero'], nf['serie'], nf['emit_nome'], _digits(nf['emit_cnpj']),
                      nf['data_emissao'], nf['total'], nf['chave']))
    nf_id = cur.lastrowid
    for it in nf['itens']:
        db.execute('''INSERT INTO nf_itens (nf_id, descricao_nf, qtd_nf, unid_nf, vlr_unit, total_item, insumo_id, qtd_entrada)
                      VALUES (?,?,?,?,?,?,?,?)''',
                   (nf_id, it['descricao'], it['qtd'], it['unid'], it['vunit'], it['total'],
                    _sugerir_insumo(db, _digits(nf['emit_cnpj']), it['descricao']), it['qtd']))
    return nf_id, True


def importar_nfe(db, nf, xml_text, enviar_estoque, usuario):
    """Grava a NF-e como documento financeiro. Retorna (status, doc_id, msg)."""
    cnpj_emp = _digits(_cfg(db, 'cnpj'))
    if nf['tipo'] == 'cancelamento':
        d = db.execute('SELECT id, numero FROM fin_documentos WHERE chave=?', (nf['chave'],)).fetchone()
        if not d:
            return 'ignorado', None, 'cancelamento de nota que não está no sistema'
        db.execute('UPDATE fin_documentos SET cancelado=1 WHERE id=?', (d['id'],))
        return 'cancelado', d['id'], f'NF {d["numero"]} marcada como cancelada'
    if db.execute('SELECT 1 FROM fin_documentos WHERE chave=?', (nf['chave'],)).fetchone():
        return 'duplicado', None, f'NF {nf["numero"]} já importada'
    emitida = cnpj_emp and _digits(nf['emit_cnpj']) == cnpj_emp
    if not emitida and cnpj_emp and nf['dest_cnpj'] and _digits(nf['dest_cnpj']) != cnpj_emp:
        return 'erro', None, f'NF {nf["numero"]} não é da empresa (nem emitente nem destinatária)'
    if emitida:
        natureza, tipo_p = 'receber', 'C'
        nome, doc = nf['dest_nome'] or 'Consumidor', nf['dest_cnpj']
    else:
        natureza, tipo_p = 'pagar', 'F'
        nome, doc = nf['emit_nome'], nf['emit_cnpj']
    pessoa_id, plano_pessoa = _pessoa(db, nome, doc, tipo_p)
    plano = plano_pessoa
    if not plano and natureza == 'receber':
        r = db.execute("SELECT id FROM fin_plano_contas WHERE codigo='1.1.01'").fetchone()
        plano = r['id'] if r else None
    nf_entrada_id = None
    if natureza == 'pagar' and enviar_estoque and nf['itens']:
        nf_entrada_id, _ = _criar_nf_entrada(db, nf)
    cur = db.execute('''INSERT INTO fin_documentos (natureza, origem, modelo, numero, serie, chave, pessoa_id,
                            data_emissao, data_competencia, valor_total, plano_conta_id, descricao,
                            nf_entrada_id, xml, criado_por)
                        VALUES (?, 'xml', ?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                     (natureza, nf['modelo'], nf['numero'], nf['serie'], nf['chave'], pessoa_id,
                      nf['data_emissao'], nf['data_emissao'], nf['total'], plano,
                      nf['natureza_op'], nf_entrada_id, xml_text, usuario))
    doc_id = cur.lastrowid
    forma = nf['pags'][0]['forma'] if len(nf['pags']) == 1 else None
    if nf['dups']:
        for d in nf['dups']:
            db.execute('INSERT INTO fin_parcelas (documento_id, numero, vencimento, valor, forma_pagamento) VALUES (?,?,?,?,?)',
                       (doc_id, d['numero'], d['vencimento'] or nf['data_emissao'], d['valor'], forma or 'Boleto'))
    else:
        db.execute('INSERT INTO fin_parcelas (documento_id, numero, vencimento, valor, forma_pagamento) VALUES (?,?,?,?,?)',
                   (doc_id, '1', nf['data_emissao'], nf['total'], forma))
    return 'ok', doc_id, f'NF {nf["numero"]} — {nome} — {natureza}'


# ─────────────────────────────── Autenticação ───────────────────────────────
@bp.app_context_processor
def _ctx():
    try:
        u = _user() if request.endpoint and request.endpoint.startswith('fin.') else None
    except Exception:
        u = None
    return dict(fin_user=u, fin_pode=lambda p: _pode(u, p))


@bp.route('/primeiro-acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    db = _db()
    if db.execute('SELECT COUNT(*) FROM fin_usuarios').fetchone()[0] > 0:
        db.close()
        return redirect(url_for('fin.login'))
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        login_ = request.form.get('login', '').strip().lower()
        s1, s2 = request.form.get('senha', ''), request.form.get('senha2', '')
        if not nome or not login_ or len(s1) < 6 or s1 != s2:
            flash('Preencha nome e login, e uma senha de pelo menos 6 caracteres repetida igual.', 'danger')
        else:
            db.execute("INSERT INTO fin_usuarios (nome, login, senha_hash, perfil) VALUES (?,?,?,'master')",
                       (nome, login_, generate_password_hash(s1)))
            _set_cfg(db, 'razao', request.form.get('razao', '').strip())
            _set_cfg(db, 'cnpj', _digits(request.form.get('cnpj', '')))
            db.commit(); db.close()
            flash('Usuário master criado. Faça o login.', 'success')
            return redirect(url_for('fin.login'))
    db.close()
    return render_template('fin/primeiro_acesso.html')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    db = _db()
    if db.execute('SELECT COUNT(*) FROM fin_usuarios').fetchone()[0] == 0:
        db.close()
        return redirect(url_for('fin.primeiro_acesso'))
    if request.method == 'POST':
        u = db.execute('SELECT * FROM fin_usuarios WHERE login=? AND ativo=1',
                       (request.form.get('login', '').strip().lower(),)).fetchone()
        if u and check_password_hash(u['senha_hash'], request.form.get('senha', '')):
            session['fin_uid'] = u['id']
            db.execute("INSERT INTO fin_log (usuario, acao) VALUES (?, 'login')", (u['login'],))
            db.commit(); db.close()
            nxt = request.args.get('next') or ''
            return redirect(nxt if nxt.startswith('/financeiro') else url_for('fin.painel'))
        flash('Login ou senha incorretos.', 'danger')
    db.close()
    return render_template('fin/login.html')


@bp.route('/logout', methods=['POST', 'GET'])
def logout():
    session.pop('fin_uid', None)
    return redirect(url_for('fin.login'))


@bp.route('/minha-senha', methods=['GET', 'POST'])
@requer()
def minha_senha():
    u = request.fin_user
    if request.method == 'POST':
        atual, s1, s2 = (request.form.get(k, '') for k in ('atual', 'senha', 'senha2'))
        if not check_password_hash(u['senha_hash'], atual):
            flash('Senha atual incorreta.', 'danger')
        elif len(s1) < 6 or s1 != s2:
            flash('A nova senha precisa ter 6+ caracteres e ser repetida igual.', 'danger')
        else:
            db = _db()
            db.execute('UPDATE fin_usuarios SET senha_hash=? WHERE id=?', (generate_password_hash(s1), u['id']))
            _log(db, 'troca de senha'); db.commit(); db.close()
            flash('Senha alterada.', 'success')
            return redirect(url_for('fin.painel'))
    return render_template('fin/minha_senha.html')


# ───────────────────────────────── Painel ───────────────────────────────────
def _saldos(db, ate=None):
    ate = ate or _hoje()
    contas = db.execute('SELECT * FROM fin_contas_bancarias WHERE ativo=1 ORDER BY id').fetchall()
    out = []
    for c in contas:
        ini = c['data_saldo_inicial'] or '0000-00-00'
        mov = db.execute('''SELECT COALESCE(SUM(CASE WHEN d.natureza='receber' THEN p.valor_pago ELSE -p.valor_pago END),0)
                            FROM fin_parcelas p JOIN fin_documentos d ON d.id=p.documento_id
                            WHERE p.conta_bancaria_id=? AND p.data_pagamento IS NOT NULL
                              AND p.data_pagamento>=? AND p.data_pagamento<=?''',
                         (c['id'], ini, ate)).fetchone()[0]
        tin = db.execute('SELECT COALESCE(SUM(valor),0) FROM fin_transferencias WHERE destino_id=? AND data>=? AND data<=?',
                         (c['id'], ini, ate)).fetchone()[0]
        tout = db.execute('SELECT COALESCE(SUM(valor),0) FROM fin_transferencias WHERE origem_id=? AND data>=? AND data<=?',
                          (c['id'], ini, ate)).fetchone()[0]
        out.append({'conta': c, 'saldo': (c['saldo_inicial'] or 0) + mov + tin - tout})
    return out


def _resumo(db, natureza):
    hoje = _hoje()
    em7 = (date.today() + timedelta(days=7)).isoformat()
    base = '''SELECT COALESCE(SUM(p.valor),0), COUNT(*) FROM fin_parcelas p
              JOIN fin_documentos d ON d.id=p.documento_id
              WHERE d.natureza=? AND d.cancelado=0 AND p.data_pagamento IS NULL AND '''
    return {
        'atrasado': db.execute(base + 'p.vencimento < ?', (natureza, hoje)).fetchone(),
        'hoje': db.execute(base + 'p.vencimento = ?', (natureza, hoje)).fetchone(),
        'semana': db.execute(base + 'p.vencimento > ? AND p.vencimento <= ?', (natureza, hoje, em7)).fetchone(),
        'total': db.execute(base + '1=1', (natureza,)).fetchone(),
    }


@bp.route('/')
@requer()
def painel():
    db = _db()
    u = request.fin_user
    saldos = _saldos(db) if _pode(u, 'perm_fluxo') else None
    pend_nf = db.execute('''SELECT COUNT(*) FROM nf_entradas ne WHERE NOT EXISTS
                            (SELECT 1 FROM fin_documentos d WHERE d.nf_entrada_id = ne.id)''').fetchone()[0]
    sem_plano = db.execute('SELECT COUNT(*) FROM fin_documentos WHERE plano_conta_id IS NULL AND cancelado=0').fetchone()[0]
    ctx = dict(saldos=saldos, pagar=_resumo(db, 'pagar'), receber=_resumo(db, 'receber'),
               pend_nf=pend_nf, sem_plano=sem_plano, sem_cnpj=not _cfg(db, 'cnpj'),
               sem_contas=db.execute('SELECT COUNT(*) FROM fin_contas_bancarias').fetchone()[0] == 0)
    db.close()
    return render_template('fin/painel.html', **ctx)


# ─────────────────────────── Contas a pagar/receber ─────────────────────────
@bp.route('/<any(pagar,receber):natureza>')
@requer()
def lista(natureza):
    db = _db()
    hoje = _hoje()
    status = request.args.get('status', 'abertos')
    de, ate = request.args.get('de', ''), request.args.get('ate', '')
    pessoa_q = request.args.get('q', '').strip()
    plano_id = request.args.get('plano', '')
    sql = '''SELECT p.*, d.numero AS doc_numero, d.modelo, d.descricao, d.id AS doc_id, d.cancelado,
                    d.data_emissao, pe.nome AS pessoa, pc.codigo AS plano_codigo, pc.nome AS plano_nome,
                    cb.nome AS conta_nome
             FROM fin_parcelas p JOIN fin_documentos d ON d.id=p.documento_id
             LEFT JOIN fin_pessoas pe ON pe.id=d.pessoa_id
             LEFT JOIN fin_plano_contas pc ON pc.id=d.plano_conta_id
             LEFT JOIN fin_contas_bancarias cb ON cb.id=p.conta_bancaria_id
             WHERE d.natureza=? AND d.cancelado=0'''
    args = [natureza]
    campo_data = 'p.vencimento'
    if status == 'abertos':
        sql += ' AND p.data_pagamento IS NULL'
    elif status == 'atrasados':
        sql += ' AND p.data_pagamento IS NULL AND p.vencimento < ?'; args.append(hoje)
    elif status == 'pagos':
        sql += ' AND p.data_pagamento IS NOT NULL'; campo_data = 'p.data_pagamento'
    if de:
        sql += f' AND {campo_data} >= ?'; args.append(de)
    if ate:
        sql += f' AND {campo_data} <= ?'; args.append(ate)
    if pessoa_q:
        sql += ' AND (pe.nome LIKE ? OR d.numero LIKE ? OR d.descricao LIKE ?)'; args += [f'%{pessoa_q}%'] * 3
    if plano_id == 'sem':
        sql += ' AND d.plano_conta_id IS NULL'
    elif plano_id:
        sql += ' AND d.plano_conta_id = ?'; args.append(plano_id)
    sql += f' ORDER BY {campo_data} {"DESC" if status == "pagos" else "ASC"}, p.id LIMIT 1000'
    rows = db.execute(sql, args).fetchall()
    parcelas = [dict(r, status=_status_parcela(r, hoje)) for r in rows]
    total = sum((r['valor_pago'] if r['data_pagamento'] else r['valor']) or 0 for r in parcelas)
    ctx = dict(natureza=natureza, parcelas=parcelas, total=total, status=status, de=de, ate=ate,
               q=pessoa_q, plano_sel=plano_id, hoje=hoje,
               planos=_plano_analiticas(db),
               contas=db.execute('SELECT * FROM fin_contas_bancarias WHERE ativo=1').fetchall(),
               formas=FORMAS_PGTO)
    db.close()
    return render_template('fin/lista.html', **ctx)


@bp.route('/baixa-lote', methods=['POST'])
@requer('perm_baixar')
def baixa_lote():
    ids = [int(i) for i in request.form.getlist('parc') if i.isdigit()]
    data_pg = request.form.get('data_pagamento') or _hoje()
    conta = request.form.get('conta_bancaria_id') or None
    forma = request.form.get('forma_pagamento') or None
    if not ids:
        flash('Selecione ao menos uma parcela.', 'warning')
        return redirect(request.referrer or url_for('fin.painel'))
    if not conta:
        flash('Escolha a conta bancária da baixa.', 'warning')
        return redirect(request.referrer or url_for('fin.painel'))
    db = _db()
    u = request.fin_user
    n = 0
    for pid in ids:
        cur = db.execute('''UPDATE fin_parcelas SET data_pagamento=?, valor_pago=valor, conta_bancaria_id=?,
                              forma_pagamento=COALESCE(?, forma_pagamento), baixado_por=?,
                              baixado_em=datetime('now','localtime')
                            WHERE id=? AND data_pagamento IS NULL''', (data_pg, conta, forma, u['login'], pid))
        n += cur.rowcount
    _log(db, 'baixa em lote', f'{n} parcelas em {data_pg}')
    db.commit(); db.close()
    flash(f'{n} parcela(s) baixada(s) em {data_pg[8:10]}/{data_pg[5:7]}/{data_pg[:4]}.', 'success')
    return redirect(request.referrer or url_for('fin.painel'))


# ───────────────────────────────── Documento ────────────────────────────────
def _salvar_parcelas_form(db, doc_id):
    """Lê parcelas do formulário (venc_N, valor_N, forma_N, num_N)."""
    idx = sorted({k.split('_', 1)[1] for k in request.form if k.startswith('valor_')}, key=lambda x: int(x))
    total = 0
    for i in idx:
        v = _num(request.form.get(f'valor_{i}'))
        if v <= 0:
            continue
        total += v
        db.execute('INSERT INTO fin_parcelas (documento_id, numero, vencimento, valor, forma_pagamento) VALUES (?,?,?,?,?)',
                   (doc_id, request.form.get(f'num_{i}') or i, request.form.get(f'venc_{i}') or _hoje(),
                    v, request.form.get(f'forma_{i}') or None))
    return total


@bp.route('/novo/<any(pagar,receber):natureza>', methods=['GET', 'POST'])
@requer()
def novo(natureza):
    db = _db()
    nf_entrada = None
    nf_id = request.args.get('nf_entrada', type=int)
    if nf_id:
        nf_entrada = db.execute('SELECT * FROM nf_entradas WHERE id=?', (nf_id,)).fetchone()
    if request.method == 'POST':
        nome = request.form.get('pessoa', '').strip()
        if not nome:
            flash('Informe o fornecedor/cliente.', 'danger')
        else:
            pessoa_id, plano_pessoa = _pessoa(db, nome, request.form.get('cnpj', ''),
                                              'F' if natureza == 'pagar' else 'C')
            plano = request.form.get('plano_conta_id') or plano_pessoa
            emissao = request.form.get('data_emissao') or _hoje()
            cur = db.execute('''INSERT INTO fin_documentos (natureza, origem, modelo, numero, serie, pessoa_id,
                                    data_emissao, data_competencia, valor_total, plano_conta_id, descricao,
                                    nf_entrada_id, criado_por)
                                VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?)''',
                             (natureza, 'pdf' if request.form.get('nf_entrada_id') else 'manual',
                              request.form.get('modelo'), request.form.get('numero'), request.form.get('serie'),
                              pessoa_id, emissao, request.form.get('data_competencia') or emissao,
                              plano or None, request.form.get('descricao'),
                              request.form.get('nf_entrada_id') or None, request.fin_user['login']))
            doc_id = cur.lastrowid
            total = _salvar_parcelas_form(db, doc_id)
            if total <= 0:
                db.rollback(); db.close()
                flash('Informe ao menos uma parcela com valor.', 'danger')
                return redirect(request.url)
            db.execute('UPDATE fin_documentos SET valor_total=? WHERE id=?', (total, doc_id))
            if request.form.get('lembrar_plano') and plano:
                db.execute('UPDATE fin_pessoas SET plano_conta_id=? WHERE id=?', (plano, pessoa_id))
            _log(db, f'novo lançamento a {natureza}', f'doc {doc_id} {nome} {total:.2f}')
            db.commit(); db.close()
            flash('Lançamento criado.', 'success')
            return redirect(url_for('fin.documento', doc_id=doc_id))
    ctx = dict(natureza=natureza, nf_entrada=nf_entrada, modelos=MODELOS, formas=FORMAS_PGTO,
               planos=_plano_analiticas(db, 'D' if natureza == 'pagar' else 'R'),
               pessoas=db.execute("SELECT nome, cnpj_cpf, plano_conta_id FROM fin_pessoas WHERE ativo=1 ORDER BY nome").fetchall(),
               hoje=_hoje())
    db.close()
    return render_template('fin/novo.html', **ctx)


@bp.route('/documento/<int:doc_id>', methods=['GET', 'POST'])
@requer()
def documento(doc_id):
    db = _db()
    d = db.execute('''SELECT d.*, pe.nome AS pessoa, pe.cnpj_cpf, pe.plano_conta_id AS plano_pessoa
                      FROM fin_documentos d LEFT JOIN fin_pessoas pe ON pe.id=d.pessoa_id
                      WHERE d.id=?''', (doc_id,)).fetchone()
    if not d:
        db.close(); abort(404)
    u = request.fin_user
    if request.method == 'POST':
        acao = request.form.get('acao')
        if acao == 'dados':
            plano = request.form.get('plano_conta_id') or None
            db.execute('''UPDATE fin_documentos SET plano_conta_id=?, descricao=?, data_competencia=?,
                          numero=?, modelo=? WHERE id=?''',
                       (plano, request.form.get('descricao'), request.form.get('data_competencia') or d['data_emissao'],
                        request.form.get('numero'), request.form.get('modelo'), doc_id))
            if request.form.get('lembrar_plano') and plano:
                db.execute('UPDATE fin_pessoas SET plano_conta_id=? WHERE id=?', (plano, d['pessoa_id']))
            _log(db, 'editou documento', str(doc_id)); flash('Dados salvos.', 'success')
        elif acao == 'parcela':
            pid = request.form.get('parcela_id', type=int)
            p = db.execute('SELECT * FROM fin_parcelas WHERE id=? AND documento_id=?', (pid, doc_id)).fetchone()
            if p and not p['data_pagamento']:
                db.execute('UPDATE fin_parcelas SET vencimento=?, valor=?, forma_pagamento=? WHERE id=?',
                           (request.form.get('vencimento'), _num(request.form.get('valor')),
                            request.form.get('forma_pagamento') or None, pid))
                _recalc_total(db, doc_id)
                _log(db, 'editou parcela', str(pid)); flash('Parcela atualizada.', 'success')
        elif acao == 'add_parcela':
            v = _num(request.form.get('valor'))
            if v > 0:
                n = db.execute('SELECT COUNT(*) FROM fin_parcelas WHERE documento_id=?', (doc_id,)).fetchone()[0] + 1
                db.execute('INSERT INTO fin_parcelas (documento_id, numero, vencimento, valor, forma_pagamento) VALUES (?,?,?,?,?)',
                           (doc_id, str(n), request.form.get('vencimento') or _hoje(), v,
                            request.form.get('forma_pagamento') or None))
                _recalc_total(db, doc_id); flash('Parcela adicionada.', 'success')
        elif acao == 'baixar' and _pode(u, 'perm_baixar'):
            pid = request.form.get('parcela_id', type=int)
            p = db.execute('SELECT * FROM fin_parcelas WHERE id=? AND documento_id=?', (pid, doc_id)).fetchone()
            conta = request.form.get('conta_bancaria_id')
            if not conta:
                flash('Escolha a conta bancária.', 'warning')
            elif p and not p['data_pagamento']:
                juros, desc = _num(request.form.get('juros')), _num(request.form.get('desconto'))
                pago = _num(request.form.get('valor_pago'), None)
                if pago is None:
                    pago = p['valor'] + juros - desc
                db.execute('''UPDATE fin_parcelas SET data_pagamento=?, valor_pago=?, juros=?, desconto=?,
                                conta_bancaria_id=?, forma_pagamento=COALESCE(?, forma_pagamento), obs=?,
                                baixado_por=?, baixado_em=datetime('now','localtime') WHERE id=?''',
                           (request.form.get('data_pagamento') or _hoje(), pago, juros, desc, conta,
                            request.form.get('forma_pagamento') or None, request.form.get('obs'), u['login'], pid))
                _log(db, 'baixa', f'parcela {pid} R$ {pago:.2f}'); flash('Baixa registrada.', 'success')
        elif acao == 'estornar' and _pode(u, 'perm_baixar'):
            pid = request.form.get('parcela_id', type=int)
            db.execute('''UPDATE fin_parcelas SET data_pagamento=NULL, valor_pago=NULL, juros=0, desconto=0,
                            baixado_por=NULL, baixado_em=NULL WHERE id=? AND documento_id=?''', (pid, doc_id))
            _log(db, 'estorno de baixa', str(pid)); flash('Baixa estornada.', 'success')
        elif acao == 'del_parcela' and _pode(u, 'perm_excluir'):
            pid = request.form.get('parcela_id', type=int)
            db.execute('DELETE FROM fin_parcelas WHERE id=? AND documento_id=? AND data_pagamento IS NULL', (pid, doc_id))
            _recalc_total(db, doc_id); _log(db, 'excluiu parcela', str(pid))
        elif acao == 'cancelar' and _pode(u, 'perm_excluir'):
            db.execute('UPDATE fin_documentos SET cancelado=1-cancelado WHERE id=?', (doc_id,))
            _log(db, 'cancelou/reativou documento', str(doc_id)); flash('Situação do documento alterada.', 'success')
        elif acao == 'excluir' and _pode(u, 'perm_excluir'):
            if db.execute('SELECT 1 FROM fin_parcelas WHERE documento_id=? AND data_pagamento IS NOT NULL', (doc_id,)).fetchone():
                flash('Estorne as baixas antes de excluir.', 'warning')
            else:
                db.execute('DELETE FROM fin_parcelas WHERE documento_id=?', (doc_id,))
                db.execute('DELETE FROM fin_documentos WHERE id=?', (doc_id,))
                _log(db, 'excluiu documento', f'{doc_id} {d["pessoa"]} {d["valor_total"]}')
                db.commit(); db.close()
                flash('Lançamento excluído. A NF continua na Entrada NF (estoque).', 'success')
                return redirect(url_for('fin.lista', natureza=d['natureza']))
        elif acao == 'estoque' and d['natureza'] == 'pagar' and d['xml'] and not d['nf_entrada_id']:
            nf = parse_nfe_xml(d['xml'].encode('utf-8'))
            nf_id, _ = _criar_nf_entrada(db, nf)
            db.execute('UPDATE fin_documentos SET nf_entrada_id=? WHERE id=?', (nf_id, doc_id))
            db.commit(); db.close()
            return redirect(url_for('nf_confirmar', nf_id=nf_id))
        db.commit(); db.close()
        return redirect(url_for('fin.documento', doc_id=doc_id))
    parcelas = [dict(p, status=_status_parcela(p)) for p in db.execute(
        '''SELECT p.*, cb.nome AS conta_nome FROM fin_parcelas p
           LEFT JOIN fin_contas_bancarias cb ON cb.id=p.conta_bancaria_id
           WHERE documento_id=? ORDER BY vencimento, id''', (doc_id,)).fetchall()]
    nf_entrada = db.execute('SELECT * FROM nf_entradas WHERE id=?', (d['nf_entrada_id'],)).fetchone() if d['nf_entrada_id'] else None
    itens = []
    if d['xml']:
        try:
            itens = parse_nfe_xml(d['xml'].encode('utf-8')).get('itens', [])
        except Exception:
            itens = []
    ctx = dict(d=d, parcelas=parcelas, nf_entrada=nf_entrada, itens=itens, modelos=MODELOS, formas=FORMAS_PGTO,
               planos=_plano_analiticas(db, 'D' if d['natureza'] == 'pagar' else 'R'),
               contas=db.execute('SELECT * FROM fin_contas_bancarias WHERE ativo=1').fetchall(), hoje=_hoje())
    db.close()
    return render_template('fin/documento.html', **ctx)


def _recalc_total(db, doc_id):
    db.execute('UPDATE fin_documentos SET valor_total=(SELECT COALESCE(SUM(valor),0) FROM fin_parcelas WHERE documento_id=?) WHERE id=?',
               (doc_id, doc_id))


# ──────────────────────────────── Importação ────────────────────────────────
@bp.route('/importar', methods=['GET', 'POST'])
@requer()
def importar():
    db = _db()
    resultado = None
    if request.method == 'POST':
        if not _cfg(db, 'cnpj'):
            db.close()
            flash('Cadastre o CNPJ da empresa em Cadastros → Empresa antes de importar.', 'warning')
            return redirect(url_for('fin.config'))
        enviar = bool(request.form.get('estoque'))
        resultado = []
        for nome, data in _arquivos_xml(request.files.getlist('arquivos')):
            if data is None:
                resultado.append(('erro', None, f'{nome}: arquivo ZIP inválido')); continue
            try:
                nf = parse_nfe_xml(data)
                try:
                    txt = data.decode('utf-8')
                except UnicodeDecodeError:
                    txt = data.decode('latin-1')
                st, doc_id, msg = importar_nfe(db, nf, txt, enviar, request.fin_user['login'])
            except ValueError as e:
                st, doc_id, msg = 'erro', None, f'{nome}: {e}'
            resultado.append((st, doc_id, msg))
        ok = sum(1 for r in resultado if r[0] == 'ok')
        _log(db, 'importou XML', f'{ok} notas')
        db.commit()
        if not resultado:
            flash('Nenhum XML encontrado nos arquivos enviados.', 'warning')
    pend = db.execute('''SELECT ne.* FROM nf_entradas ne WHERE NOT EXISTS
                         (SELECT 1 FROM fin_documentos d WHERE d.nf_entrada_id = ne.id)
                         ORDER BY ne.data_emissao DESC''').fetchall()
    db.close()
    return render_template('fin/importar.html', resultado=resultado, pend=pend)


# ─────────────────────────────── Fluxo de caixa ─────────────────────────────
def _periodo_key(d, agrup):
    dt = date.fromisoformat(d)
    if agrup == 'dia':
        return d
    if agrup == 'semana':
        ini = dt - timedelta(days=dt.weekday())
        return ini.isoformat()
    return d[:7]


def _periodos(ini, fim, agrup):
    out, cur = [], ini
    while cur <= fim:
        k = _periodo_key(cur.isoformat(), agrup)
        if k not in out:
            out.append(k)
        cur += timedelta(days=1)
    return out


@bp.route('/fluxo')
@requer('perm_fluxo')
def fluxo():
    db = _db()
    hoje = date.today()
    agrup = request.args.get('agrup', 'semana')
    conta_id = request.args.get('conta', type=int)
    padrao = {'dia': (hoje - timedelta(days=7), hoje + timedelta(days=30)),
              'semana': (hoje - timedelta(days=28), hoje + timedelta(days=84)),
              'mes': (hoje.replace(day=1) - timedelta(days=90), hoje + timedelta(days=270))}[agrup]
    ini = date.fromisoformat(request.args.get('de') or padrao[0].isoformat())
    fim = date.fromisoformat(request.args.get('ate') or padrao[1].isoformat())
    if agrup == 'mes':
        ini = ini.replace(day=1)
    keys = _periodos(ini, fim, agrup)
    linhas = {k: dict(periodo=k, ent_real=0, sai_real=0, ent_prev=0, sai_prev=0) for k in keys}
    filtro_c = ' AND p.conta_bancaria_id=?' if conta_id else ''
    a = [conta_id] if conta_id else []
    # realizado
    for r in db.execute(f'''SELECT p.data_pagamento AS dt, d.natureza, p.valor_pago AS v
                            FROM fin_parcelas p JOIN fin_documentos d ON d.id=p.documento_id
                            WHERE p.data_pagamento BETWEEN ? AND ?{filtro_c}''',
                        [ini.isoformat(), fim.isoformat()] + a):
        k = _periodo_key(r['dt'], agrup)
        if k in linhas:
            linhas[k]['ent_real' if r['natureza'] == 'receber' else 'sai_real'] += r['v'] or 0
    # transferências (só quando filtra uma conta)
    if conta_id:
        for r in db.execute('SELECT * FROM fin_transferencias WHERE data BETWEEN ? AND ? AND (origem_id=? OR destino_id=?)',
                            (ini.isoformat(), fim.isoformat(), conta_id, conta_id)):
            k = _periodo_key(r['data'], agrup)
            if k in linhas:
                linhas[k]['ent_real' if r['destino_id'] == conta_id else 'sai_real'] += r['valor']
    # previsto: em aberto; vencidas entram em hoje
    atras_ent = atras_sai = 0
    for r in db.execute('''SELECT p.vencimento AS dt, d.natureza, p.valor AS v
                           FROM fin_parcelas p JOIN fin_documentos d ON d.id=p.documento_id
                           WHERE d.cancelado=0 AND p.data_pagamento IS NULL AND p.vencimento <= ?''',
                        (fim.isoformat(),)):
        dt = r['dt'] if r['dt'] >= hoje.isoformat() else hoje.isoformat()
        if r['dt'] < hoje.isoformat():
            if r['natureza'] == 'receber':
                atras_ent += r['v']
            else:
                atras_sai += r['v']
        k = _periodo_key(dt, agrup)
        if k in linhas:
            linhas[k]['ent_prev' if r['natureza'] == 'receber' else 'sai_prev'] += r['v'] or 0
    # saldo inicial = saldo realizado no dia anterior ao início
    saldos_ini = _saldos(db, (ini - timedelta(days=1)).isoformat())
    saldo = sum(s['saldo'] for s in saldos_ini if not conta_id or s['conta']['id'] == conta_id)
    saldo_ini = saldo
    out = []
    serie_lbl, serie_val = [], []
    for k in keys:
        l = linhas[k]
        saldo += l['ent_real'] - l['sai_real'] + l['ent_prev'] - l['sai_prev']
        l['saldo'] = saldo
        l['futuro'] = _fim_periodo(k, agrup) >= hoje.isoformat()
        out.append(l)
        serie_lbl.append(_label_periodo(k, agrup)); serie_val.append(round(saldo, 2))
    ctx = dict(linhas=out, agrup=agrup, de=ini.isoformat(), ate=fim.isoformat(), conta_id=conta_id,
               contas=db.execute('SELECT * FROM fin_contas_bancarias WHERE ativo=1').fetchall(),
               saldo_ini=saldo_ini, atras_ent=atras_ent, atras_sai=atras_sai,
               saldos=_saldos(db), serie_lbl=serie_lbl, serie_val=serie_val,
               label=lambda k: _label_periodo(k, agrup))
    db.close()
    return render_template('fin/fluxo.html', **ctx)


def _fim_periodo(k, agrup):
    if agrup == 'dia':
        return k
    if agrup == 'semana':
        return (date.fromisoformat(k) + timedelta(days=6)).isoformat()
    return k + '-31'


MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']


def _label_periodo(k, agrup):
    if agrup == 'dia':
        return f'{k[8:10]}/{k[5:7]}'
    if agrup == 'semana':
        f = date.fromisoformat(k) + timedelta(days=6)
        return f'{k[8:10]}/{k[5:7]} a {f.day:02d}/{f.month:02d}'
    return f'{MESES[int(k[5:7]) - 1]}/{k[2:4]}'


# ──────────────────────────────────── DRE ───────────────────────────────────
@bp.route('/dre')
@requer('perm_fluxo')
def dre():
    db = _db()
    ano = request.args.get('ano', type=int) or date.today().year
    regime = request.args.get('regime', 'caixa')
    meses = [f'{ano}-{m:02d}' for m in range(1, 13)]
    if regime == 'caixa':
        q = '''SELECT d.plano_conta_id AS pid, substr(p.data_pagamento,1,7) AS mes, SUM(p.valor_pago) AS v
               FROM fin_parcelas p JOIN fin_documentos d ON d.id=p.documento_id
               WHERE d.cancelado=0 AND p.data_pagamento LIKE ? GROUP BY 1,2'''
    else:
        q = '''SELECT d.plano_conta_id AS pid, substr(d.data_competencia,1,7) AS mes, SUM(p.valor) AS v
               FROM fin_parcelas p JOIN fin_documentos d ON d.id=p.documento_id
               WHERE d.cancelado=0 AND d.data_competencia LIKE ? GROUP BY 1,2'''
    valores = {}
    for r in db.execute(q, (f'{ano}-%',)):
        valores.setdefault(r['pid'], {})[r['mes']] = r['v'] or 0
    plano = db.execute('SELECT * FROM fin_plano_contas WHERE ativo=1 ORDER BY codigo').fetchall()
    cod_de = {p['id']: p['codigo'] for p in plano}
    # soma por código (inclui grupos)
    tot = {}
    for pid, por_mes in valores.items():
        cod = cod_de.get(pid)
        alvos = []
        if cod:
            partes = cod.split('.')
            alvos = ['.'.join(partes[:i]) for i in range(1, len(partes) + 1)]
        else:
            alvos = ['?']
        for a in alvos:
            t = tot.setdefault(a, {m: 0 for m in meses})
            for m, v in por_mes.items():
                if m in t:
                    t[m] += v

    def soma(cod):
        t = tot.get(cod, {})
        return [t.get(m, 0) for m in meses]

    linhas = []
    for p in plano:
        vals = soma(p['codigo'])
        nivel = p['codigo'].count('.')
        if nivel >= 1 and not any(vals):
            continue
        linhas.append(dict(codigo=p['codigo'], nome=p['nome'], nivel=nivel, vals=vals, total=sum(vals)))

    def sub(*cods, menos=()):
        r = [0] * 12
        for c in cods:
            r = [a + b for a, b in zip(r, soma(c))]
        for c in menos:
            r = [a - b for a, b in zip(r, soma(c))]
        return r
    rec_liq = sub('1', menos=('2',))
    lucro_bruto = [a - b for a, b in zip(rec_liq, soma('3'))]
    res_oper = [a - b for a, b in zip(lucro_bruto, soma('4'))]
    res_liq = [a - b for a, b in zip(res_oper, soma('5'))]
    apos_inv = [a - b + c - d for a, b, c, d in zip(res_liq, soma('6'), soma('7.1'), soma('7.2'))]
    marcos = {
        '2': ('= RECEITA LÍQUIDA', rec_liq),
        '3': ('= LUCRO BRUTO', lucro_bruto),
        '4': ('= RESULTADO OPERACIONAL', res_oper),
        '5': ('= RESULTADO LÍQUIDO', res_liq),
        '7': ('= GERAÇÃO DE CAIXA (após investimentos e não operacionais)', apos_inv),
    }
    sem_plano = soma('?')
    ctx = dict(ano=ano, regime=regime, meses=meses, linhas=linhas, marcos=marcos,
               sem_plano=sem_plano if any(sem_plano) else None, MESES=MESES)
    db.close()
    return render_template('fin/dre.html', **ctx)


# ──────────────────────────────── Cadastros ─────────────────────────────────
@bp.route('/cadastros/empresa', methods=['GET', 'POST'])
@requer('master')
def config():
    db = _db()
    if request.method == 'POST':
        _set_cfg(db, 'razao', request.form.get('razao', '').strip())
        _set_cfg(db, 'cnpj', _digits(request.form.get('cnpj', '')))
        _log(db, 'alterou dados da empresa'); db.commit()
        flash('Dados da empresa salvos.', 'success')
    ctx = dict(razao=_cfg(db, 'razao'), cnpj=_cfg(db, 'cnpj'))
    db.close()
    return render_template('fin/config.html', **ctx)


@bp.route('/cadastros/contas', methods=['GET', 'POST'])
@requer('master')
def contas():
    db = _db()
    if request.method == 'POST':
        cid = request.form.get('id', type=int)
        vals = (request.form.get('nome', '').strip(), request.form.get('tipo', 'banco'),
                request.form.get('banco'), request.form.get('agencia'), request.form.get('conta'),
                _num(request.form.get('saldo_inicial')), request.form.get('data_saldo_inicial') or _hoje(),
                1 if request.form.get('ativo', '1') == '1' else 0)
        if not vals[0]:
            flash('Informe o nome da conta.', 'danger')
        elif cid:
            db.execute('''UPDATE fin_contas_bancarias SET nome=?, tipo=?, banco=?, agencia=?, conta=?,
                          saldo_inicial=?, data_saldo_inicial=?, ativo=? WHERE id=?''', vals + (cid,))
            _log(db, 'editou conta bancária', vals[0]); flash('Conta salva.', 'success')
        else:
            db.execute('''INSERT INTO fin_contas_bancarias (nome, tipo, banco, agencia, conta, saldo_inicial,
                          data_saldo_inicial, ativo) VALUES (?,?,?,?,?,?,?,?)''', vals)
            _log(db, 'criou conta bancária', vals[0]); flash('Conta criada.', 'success')
        db.commit()
    ctx = dict(contas=db.execute('SELECT * FROM fin_contas_bancarias ORDER BY ativo DESC, id').fetchall(),
               saldos={s['conta']['id']: s['saldo'] for s in _saldos(db)}, hoje=_hoje())
    db.close()
    return render_template('fin/contas.html', **ctx)


@bp.route('/transferencia', methods=['POST'])
@requer('perm_baixar')
def transferencia():
    o, d_ = request.form.get('origem_id', type=int), request.form.get('destino_id', type=int)
    v = _num(request.form.get('valor'))
    if not o or not d_ or o == d_ or v <= 0:
        flash('Escolha contas diferentes e um valor.', 'danger')
    else:
        db = _db()
        db.execute('INSERT INTO fin_transferencias (data, origem_id, destino_id, valor, obs, criado_por) VALUES (?,?,?,?,?,?)',
                   (request.form.get('data') or _hoje(), o, d_, v, request.form.get('obs'), request.fin_user['login']))
        _log(db, 'transferência', f'{o}->{d_} {v:.2f}'); db.commit(); db.close()
        flash('Transferência registrada.', 'success')
    return redirect(request.referrer or url_for('fin.painel'))


@bp.route('/cadastros/plano', methods=['GET', 'POST'])
@requer('master')
def plano():
    db = _db()
    if request.method == 'POST':
        acao = request.form.get('acao')
        if acao == 'salvar':
            pid = request.form.get('id', type=int)
            cod = request.form.get('codigo', '').strip()
            nome = request.form.get('nome', '').strip()
            tipo = request.form.get('tipo', 'D')
            if not re.fullmatch(r'\d+(\.\d+)*', cod) or not nome:
                flash('Código no formato 1.2.03 e nome são obrigatórios.', 'danger')
            else:
                try:
                    if pid:
                        db.execute('UPDATE fin_plano_contas SET codigo=?, nome=?, tipo=? WHERE id=?', (cod, nome, tipo, pid))
                    else:
                        db.execute('INSERT INTO fin_plano_contas (codigo, nome, tipo) VALUES (?,?,?)', (cod, nome, tipo))
                    _log(db, 'plano de contas', f'{cod} {nome}')
                    db.commit(); flash('Conta salva.', 'success')
                except Exception:
                    flash(f'Já existe uma conta com o código {cod}.', 'danger')
        elif acao == 'toggle':
            db.execute('UPDATE fin_plano_contas SET ativo=1-ativo WHERE id=?', (request.form.get('id', type=int),))
            db.commit()
    rows = db.execute('''SELECT pc.*, (SELECT COUNT(*) FROM fin_documentos d WHERE d.plano_conta_id=pc.id) AS usos
                         FROM fin_plano_contas pc ORDER BY codigo''').fetchall()
    db.close()
    return render_template('fin/plano.html', rows=rows)


@bp.route('/cadastros/pessoas', methods=['GET', 'POST'])
@requer()
def pessoas():
    db = _db()
    if request.method == 'POST':
        pid = request.form.get('id', type=int)
        db.execute('UPDATE fin_pessoas SET nome=?, cnpj_cpf=?, tipo=?, plano_conta_id=? WHERE id=?',
                   (request.form.get('nome', '').strip(), _digits(request.form.get('cnpj_cpf')) or None,
                    request.form.get('tipo', 'F'), request.form.get('plano_conta_id') or None, pid))
        if request.form.get('aplicar'):
            n = db.execute('''UPDATE fin_documentos SET plano_conta_id=? WHERE pessoa_id=? AND plano_conta_id IS NULL''',
                           (request.form.get('plano_conta_id') or None, pid)).rowcount
            flash(f'Plano aplicado a {n} lançamento(s) sem classificação.', 'info')
        _log(db, 'editou pessoa', str(pid)); db.commit()
        flash('Cadastro salvo.', 'success')
    rows = db.execute('''SELECT pe.*, pc.codigo, pc.nome AS plano_nome,
                            (SELECT COUNT(*) FROM fin_documentos d WHERE d.pessoa_id=pe.id) AS docs
                         FROM fin_pessoas pe LEFT JOIN fin_plano_contas pc ON pc.id=pe.plano_conta_id
                         ORDER BY pe.nome''').fetchall()
    ctx = dict(rows=rows, planos=_plano_analiticas(db))
    db.close()
    return render_template('fin/pessoas.html', **ctx)


@bp.route('/cadastros/usuarios', methods=['GET', 'POST'])
@requer('master')
def usuarios():
    db = _db()
    if request.method == 'POST':
        uid = request.form.get('id', type=int)
        nome = request.form.get('nome', '').strip()
        login_ = request.form.get('login', '').strip().lower()
        perfil = request.form.get('perfil', 'usuario')
        perms = [1 if request.form.get(k) else 0 for k, _ in PERMISSOES]
        senha = request.form.get('senha', '')
        ativo = 1 if request.form.get('ativo', '1') == '1' else 0
        if uid == request.fin_user['id'] and (perfil != 'master' or not ativo):
            flash('Você não pode tirar o seu próprio acesso master.', 'warning')
        elif not nome or not login_:
            flash('Nome e login são obrigatórios.', 'danger')
        elif senha and len(senha) < 6:
            flash('A senha precisa ter pelo menos 6 caracteres.', 'danger')
        elif not uid and not senha:
            flash('Defina uma senha inicial para o novo usuário.', 'danger')
        else:
            try:
                if uid:
                    db.execute('''UPDATE fin_usuarios SET nome=?, login=?, perfil=?, perm_baixar=?, perm_fluxo=?,
                                  perm_excluir=?, ativo=? WHERE id=?''', (nome, login_, perfil, *perms, ativo, uid))
                    if senha:
                        db.execute('UPDATE fin_usuarios SET senha_hash=? WHERE id=?', (generate_password_hash(senha), uid))
                else:
                    db.execute('''INSERT INTO fin_usuarios (nome, login, senha_hash, perfil, perm_baixar, perm_fluxo, perm_excluir, ativo)
                                  VALUES (?,?,?,?,?,?,?,?)''', (nome, login_, generate_password_hash(senha), perfil, *perms, ativo))
                _log(db, 'usuário salvo', login_); db.commit()
                flash('Usuário salvo.', 'success')
            except Exception:
                flash(f'O login "{login_}" já existe.', 'danger')
    rows = db.execute('SELECT * FROM fin_usuarios ORDER BY perfil, nome').fetchall()
    log = db.execute('SELECT * FROM fin_log ORDER BY id DESC LIMIT 60').fetchall()
    db.close()
    return render_template('fin/usuarios.html', rows=rows, permissoes=PERMISSOES, log=log)


def init_app(app, get_db):
    global _get_db
    _get_db = get_db
    app.register_blueprint(bp)
    init_tables()
