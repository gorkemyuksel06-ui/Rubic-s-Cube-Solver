import cv2
import numpy as np
import kociemba
import time
import threading
import random

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    print("[WARNING] RPi.GPIO not found. Motors will not spin.")
    GPIO_AVAILABLE = False

# ══════════════════════════════════════════
# 1. MOTOR CONFIG
# ══════════════════════════════════════════

MOTOR_PINS = {
    'U': {'step': 2,  'dir': 3},
    'D': {'step': 4,  'dir': 14},
    'F': {'step': 15, 'dir': 18},
    'B': {'step': 17, 'dir': 27},
    'L': {'step': 22, 'dir': 23},
    'R': {'step': 24, 'dir': 25},
}
STEPS_PER_90 = 50
STEP_DELAY   = 0.003

def setup_motors():
    if not GPIO_AVAILABLE:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pins in MOTOR_PINS.values():
        GPIO.setup(pins['step'], GPIO.OUT)
        GPIO.setup(pins['dir'],  GPIO.OUT)
    print("[MOTORS] Initialized.")

def rotate_motor(face, move_type):
    print(f"  -> [{face}] {move_type}")
    if not GPIO_AVAILABLE:
        time.sleep(0.4)
        return
    pins     = MOTOR_PINS[face]
    step_pin = pins['step']
    dir_pin  = pins['dir']

    # D motoru fiziksel olarak ters bağlı, yönü tersle
    REVERSED = {'D'}

    if face in REVERSED:
        cw_signal  = GPIO.LOW
        ccw_signal = GPIO.HIGH
    else:
        cw_signal  = GPIO.HIGH
        ccw_signal = GPIO.LOW

    if   move_type == "CW":  GPIO.output(dir_pin, cw_signal);  steps = STEPS_PER_90
    elif move_type == "CCW": GPIO.output(dir_pin, ccw_signal); steps = STEPS_PER_90
    elif move_type == "180": GPIO.output(dir_pin, cw_signal);  steps = STEPS_PER_90 * 2
    else: return
    for _ in range(steps):
        GPIO.output(step_pin, GPIO.HIGH); time.sleep(STEP_DELAY)
        GPIO.output(step_pin, GPIO.LOW);  time.sleep(STEP_DELAY)
    time.sleep(0.08)

# ══════════════════════════════════════════
# 2. COLOUR & FACE DEFINITIONS
# ══════════════════════════════════════════

FACE_CENTER = {'F':'GREEN','R':'RED','B':'BLUE','L':'ORANGE','U':'WHITE','D':'YELLOW'}

COLOR_BGR = {
    'WHITE':   (255, 255, 255),
    'RED':     (30,  30,  210),
    'GREEN':   (30,  170, 30 ),
    'YELLOW':  (20,  220, 220),
    'ORANGE':  (20,  120, 255),
    'BLUE':    (200, 70,  20 ),
    'EMPTY':   (70,  70,  70 ),
    'UNKNOWN': (130, 0,   130),
}

COLOR_LETTER = {
    'WHITE':'U','RED':'R','GREEN':'F',
    'YELLOW':'D','ORANGE':'L','BLUE':'B',
    'EMPTY':'?','UNKNOWN':'?',
}

# All selectable colors for the manual color picker (popup)
ALL_COLORS = ['WHITE', 'RED', 'GREEN', 'YELLOW', 'ORANGE', 'BLUE']

SCAN_ORDER = ['F','R','B','L','U','D']

INSTRUCTIONS = {
    'F': "1/6  Show GREEN face  (white sticker on top)  ->  press F",
    'R': "2/6  Rotate LEFT  ->  Show RED face  ->  press R",
    'B': "3/6  Rotate LEFT  ->  Show BLUE face  ->  press B",
    'L': "4/6  Rotate LEFT  ->  Show ORANGE face  ->  press L",
    'U': "5/6  Rotate LEFT then DOWN  ->  Show WHITE face  ->  press U",
    'D': "6/6  Tilt DOWN twice  ->  Show YELLOW face  ->  press D",
}

# Face button definitions: (key, label, color_bgr, center_color_name)
FACE_BUTTONS = [
    ('F', 'GREEN',  (30,  160, 30 ), 'GREEN' ),
    ('R', 'RED',    (30,  30,  200), 'RED'   ),
    ('B', 'BLUE',   (180, 60,  20 ), 'BLUE'  ),
    ('L', 'ORANGE', (20,  110, 240), 'ORANGE'),
    ('U', 'WHITE',  (185, 185, 185), 'WHITE' ),
    ('D', 'YELLOW', (20,  200, 205), 'YELLOW'),
]

# ══════════════════════════════════════════
# 3. COLOUR DETECTION
# ══════════════════════════════════════════

def color_guess(h, s, v):
    if s < 90:
        return "WHITE"

    if h < 8 or h >= 160:    return "RED"
    if 8  <= h < 25:         return "ORANGE"
    if 25 <= h < 40:         return "YELLOW"
    if 40 <= h < 55:
        if v > 150:          return "YELLOW"
        else:                return "GREEN"
    if 55 <= h < 90:         return "GREEN"
    if 90 <= h < 140:        return "BLUE"

    return "RED"  # v < 60 dark pixels → kırmızı yüz

# ══════════════════════════════════════════
# 4. CUBE STATE SIMULATOR
# ══════════════════════════════════════════
#
# We need to keep cube_state in sync with the motors when we randomly mix
# the cube — otherwise after mixing, the on-screen map would still show the
# scanned (solved) state, and pressing SOLVE would do nothing useful.
#
# Each face stores 9 stickers in row-major order (indices 0..8):
#   0 1 2
#   3 4 5
#   6 7 8
#
# Rotating a face clockwise (as seen looking AT that face from outside)
# permutes its own 9 stickers AND cycles 4 strips of 3 stickers on the
# 4 adjacent faces.

def _rotate_face_cw(face_list):
    """Rotate a 9-sticker face 90° clockwise (in place)."""
    f = face_list
    # corners cycle
    f[0], f[2], f[8], f[6] = f[6], f[0], f[2], f[8]
    # edges cycle
    f[1], f[5], f[7], f[3] = f[3], f[1], f[5], f[7]

def _rotate_face_ccw(face_list):
    """Rotate a 9-sticker face 90° counter-clockwise (in place)."""
    f = face_list
    f[0], f[6], f[8], f[2] = f[2], f[0], f[6], f[8]
    f[1], f[3], f[7], f[5] = f[5], f[1], f[3], f[7]

# Adjacent-strip definitions for each face turn (CW).
# For each face, list 4 (adjacent_face, [indices]) tuples in the order the
# stickers cycle.  When face X turns CW, the stickers travel:
#   ADJ[0] -> ADJ[1] -> ADJ[2] -> ADJ[3] -> ADJ[0]
#
# Orientation convention used here matches the standard cube net:
#       U
#   L   F   R   B
#       D
# F (front) seen face-on; L on its left, R on its right, U above, D below.
# When we look AT a face, "CW" means the stickers visibly rotate clockwise.

ADJ = {
    'U': [
        ('B', [2, 1, 0]),
        ('R', [2, 1, 0]),
        ('F', [2, 1, 0]),
        ('L', [2, 1, 0]),
    ],
    'D': [
        ('F', [6, 7, 8]),
        ('R', [6, 7, 8]),
        ('B', [6, 7, 8]),
        ('L', [6, 7, 8]),
    ],
    'F': [
        ('U', [6, 7, 8]),
        ('R', [0, 3, 6]),
        ('D', [2, 1, 0]),
        ('L', [8, 5, 2]),
    ],
    'B': [
        ('U', [2, 1, 0]),
        ('L', [0, 3, 6]),
        ('D', [6, 7, 8]),
        ('R', [8, 5, 2]),
    ],
    'L': [
        ('U', [0, 3, 6]),
        ('F', [0, 3, 6]),
        ('D', [0, 3, 6]),
        ('B', [8, 5, 2]),
    ],
    'R': [
        ('U', [8, 5, 2]),
        ('B', [0, 3, 6]),
        ('D', [8, 5, 2]),
        ('F', [8, 5, 2]),
    ],
}

def apply_move(state, face, move_type):
    """
    Apply a single move to the cube state dict (in place).
    state: dict {face_letter -> list of 9 color names}
    face : 'U','D','F','B','L','R'
    move_type: 'CW', 'CCW', or '180'
    """
    if move_type == '180':
        apply_move(state, face, 'CW')
        apply_move(state, face, 'CW')
        return

    # 1) rotate the face's own stickers
    if move_type == 'CW':
        _rotate_face_cw(state[face])
    else:
        _rotate_face_ccw(state[face])

    # 2) cycle the 4 adjacent strips
    chain = ADJ[face]
    # Snapshot strip values  (each strip is a list of 3 sticker color names)
    strips = []
    for adj_face, idxs in chain:
        strips.append([state[adj_face][i] for i in idxs])

    if move_type == 'CW':
        # rotate strips forward: 0->1, 1->2, 2->3, 3->0
        new_strips = [strips[-1]] + strips[:-1]
    else:  # CCW
        # rotate strips backward
        new_strips = strips[1:] + [strips[0]]

    for (adj_face, idxs), new_vals in zip(chain, new_strips):
        for k, i in enumerate(idxs):
            state[adj_face][i] = new_vals[k]

# ══════════════════════════════════════════
# 5. SOLVER & MIXER THREADS
# ══════════════════════════════════════════

solve_state = {
    'running': False, 'solution': '', 'current_move': '',
    'move_index': 0,  'total_moves': 0, 'error': '', 'done': False,
    'mode': 'solve',   # 'solve' or 'mix'
    'mixed_hold_until': 0.0,   # timestamp until which "CUBE MIXED" stays on screen
}

def solver_thread_fn(snap):
    solve_state.update({'running':True,'error':'','solution':'',
                        'current_move':'Calculating...','move_index':0,
                        'total_moves':0,'done':False,'mode':'solve',
                        'mixed_hold_until':0.0})
    try:
        s = ''
        for face in ['U','R','F','D','L','B']:
            for idx, c in enumerate(snap[face]):
                s += COLOR_LETTER[FACE_CENTER[face]] if idx == 4 else COLOR_LETTER.get(c,'?')
        if '?' in s:
            raise ValueError("Unrecognised color. Check lighting and retry.")
        print(f"[SOLVER] {s}")
        solution = kociemba.solve(s)
        print(f"[SOLVER] Solution: {solution}")
        moves = solution.split()
        solve_state['solution']    = solution
        solve_state['total_moves'] = len(moves)
        for i, move in enumerate(moves):
            face  = move[0]
            mtype = "CW" if len(move)==1 else "CCW" if move[1]=="'" else "180"
            solve_state['move_index']   = i + 1
            solve_state['current_move'] = move
            rotate_motor(face, mtype)
        solve_state['current_move'] = 'Done!'
        solve_state['done']         = True
    except Exception as e:
        solve_state['error']        = str(e)
        solve_state['current_move'] = 'Error'
    solve_state['running'] = False


def mixer_thread_fn(state_ref, n_moves=20):
    """
    Generate a random scramble, drive the motors AND update the cube_state
    dict so the on-screen map reflects the new (mixed) state.

    state_ref: the shared cube_state dict (mutated in place).
    """
    solve_state.update({'running':True,'error':'','solution':'',
                        'current_move':'Mixing...','move_index':0,
                        'total_moves':n_moves,'done':False,'mode':'mix',
                        'mixed_hold_until':0.0})
    try:
        faces = ['U','D','F','B','L','R']
        types = ['CW','CCW','180']
        type_labels = {'CW':'', 'CCW':"'", '180':'2'}

        scramble = []
        last_face = None
        for _ in range(n_moves):
            # avoid two moves in a row on the same face (looks silly + redundant)
            choices = [f for f in faces if f != last_face]
            f = random.choice(choices)
            t = random.choice(types)
            scramble.append((f, t))
            last_face = f

        scramble_str = ' '.join(f + type_labels[t] for f, t in scramble)
        solve_state['solution'] = scramble_str
        print(f"[MIXER] Scramble: {scramble_str}")

        for i, (f, t) in enumerate(scramble):
            solve_state['move_index']   = i + 1
            solve_state['current_move'] = f + type_labels[t]
            # update on-screen state BEFORE driving the motor so the map stays
            # in sync even if the user is watching
            apply_move(state_ref, f, t)
            rotate_motor(f, t)

        solve_state['current_move'] = 'Mixed!'
        solve_state['done']         = True
        # hold the "CUBE MIXED" message for 5 seconds before the overlay closes
        solve_state['mixed_hold_until'] = time.time() + 5.0
    except Exception as e:
        solve_state['error']        = str(e)
        solve_state['current_move'] = 'Error'
    solve_state['running'] = False

# ══════════════════════════════════════════
# 6. LAYOUT CONSTANTS  (computed at startup)
# ══════════════════════════════════════════

CAM_W, CAM_H = 640, 480

SCREEN_W = 800
SCREEN_H = 480

layout = {}

def build_layout(sw, sh):
    """
    Divide the screen into:
      - Top bar:  full width, fixed height
      - Left:     camera panel
      - Right:    button panel
        - Face buttons (compacted, 2×3)
        - Action buttons: SOLVE / RANDOM MIX / RESET ALL
        - Cube Net Map (live, fills remaining space)
    """
    top_h     = max(40, int(sh * 0.08))
    content_h = sh - top_h

    cam_panel_w = CAM_W
    cam_panel_h = content_h
    cam_panel_x = 0
    cam_panel_y = top_h

    right_x = cam_panel_w
    right_w  = sw - cam_panel_w
    right_y  = top_h
    right_h  = content_h

    # Face buttons: compacted to ~50% of right height
    pad      = max(8, int(right_w * 0.04))
    btn_gap  = max(5, int(right_w * 0.025))
    n_col, n_row = 2, 3

    grid_w   = right_w - 2 * pad
    grid_h   = int(right_h * 0.36)   # compacted further to give net map more room
    btn_w    = (grid_w - (n_col-1)*btn_gap) // n_col
    btn_h    = (grid_h - (n_row-1)*btn_gap) // n_row

    grid_x   = right_x + pad
    grid_y   = right_y + pad

    # Action buttons row: SOLVE | RANDOM MIX | RESET ALL
    action_y   = grid_y + grid_h + pad
    action_h   = max(36, int(right_h * 0.09))
    action_gap = btn_gap
    total_aw   = grid_w
    solve_w    = int(total_aw * 0.38)
    mix_w      = int(total_aw * 0.34)
    reseta_w   = total_aw - solve_w - mix_w - 2*action_gap
    solve_x    = grid_x
    mix_x      = grid_x + solve_w + action_gap
    reseta_x   = mix_x + mix_w + action_gap

    # Cube net map area: fills remaining space below action buttons
    net_y = action_y + action_h + pad
    net_h = right_h - (net_y - right_y) - pad
    net_x = right_x
    net_w = right_w

    status_y = action_y + action_h + 6

    return {
        'top_h':      top_h,
        'cam_x':      cam_panel_x,
        'cam_y':      cam_panel_y,
        'cam_w':      cam_panel_w,
        'cam_h':      cam_panel_h,
        'right_x':    right_x,
        'right_y':    right_y,
        'right_w':    right_w,
        'right_h':    right_h,
        'grid_x':     grid_x,
        'grid_y':     grid_y,
        'btn_w':      btn_w,
        'btn_h':      btn_h,
        'btn_gap':    btn_gap,
        'n_col':      n_col,
        'n_row':      n_row,
        'solve_x':    solve_x,
        'solve_w':    solve_w,
        'mix_x':      mix_x,
        'mix_w':      mix_w,
        'reseta_x':   reseta_x,
        'reseta_w':   reseta_w,
        'action_y':   action_y,
        'action_h':   action_h,
        'status_y':   status_y,
        'net_x':      net_x,
        'net_y':      net_y,
        'net_w':      net_w,
        'net_h':      net_h,
        'pad':        pad,
    }

# ══════════════════════════════════════════
# 7. DRAW FUNCTIONS
# ══════════════════════════════════════════

def draw_camera_panel(canvas, frame_cam, L):
    cx = L['cam_x']
    cy = L['cam_y']
    ch = L['cam_h']
    cw = L['cam_w']

    cam_h, cam_w = frame_cam.shape[:2]
    scale  = min(cw / cam_w, ch / cam_h)
    dw     = int(cam_w * scale)
    dh     = int(cam_h * scale)
    scaled = cv2.resize(frame_cam, (dw, dh))
    ox     = cx + (cw - dw) // 2
    oy     = cy + (ch - dh) // 2
    canvas[oy:oy+dh, ox:ox+dw] = scaled

    cv2.rectangle(canvas, (cx, cy), (cx+cw-1, cy+ch-1), (60,60,60), 1)
    return ox, oy, dw, dh


def draw_cube_grid(canvas, frame_cam, ox, oy, dw, dh,
                   face, temp_colors, saved_colors, manual_select_mode=False):
    """
    Draw the 3×3 colour grid centred on the camera image.
    Returns list of (x1,y1,x2,y2) for each cell (for manual click detection).
    """
    cx = ox + dw // 2
    cy = oy + dh // 2

    box  = max(32, int(dh * 0.08))
    step = max(46, int(dh * 0.12))

    center_name = FACE_CENTER.get(face, 'UNKNOWN')
    use_saved   = len(saved_colors) == 9
    colors      = saved_colors if use_saved else temp_colors
    border_clr  = (60, 255, 60) if use_saved else (220, 220, 220)
    if manual_select_mode:
        border_clr = (0, 200, 255)   # cyan highlight when in manual mode
    fs = max(0.45, box / 50)

    cell_rects = []
    for row, dy in enumerate((-1, 0, 1)):
        for col, dx in enumerate((-1, 0, 1)):
            idx  = row * 3 + col
            rx   = cx + dx * step - box // 2
            ry   = cy + dy * step - box // 2
            rx2, ry2 = rx + box, ry + box
            cell_rects.append((rx, ry, rx2, ry2))

            if idx == 4:
                fill = COLOR_BGR[center_name]
                cv2.rectangle(canvas, (rx,ry), (rx2,ry2), fill, -1)
                cv2.rectangle(canvas, (rx,ry), (rx2,ry2), (255,255,255), 2)
                ltr = center_name[0]
                tc  = (0,0,0)
            else:
                cname = colors[idx] if idx < len(colors) else 'UNKNOWN'
                fill  = COLOR_BGR.get(cname, COLOR_BGR['UNKNOWN'])
                cv2.rectangle(canvas, (rx,ry), (rx2,ry2), fill, -1)
                cv2.rectangle(canvas, (rx,ry), (rx2,ry2), border_clr, 2)
                ltr = cname[0] if cname not in ('EMPTY','UNKNOWN') else '?'
                tc  = (0,0,0) if cname == 'WHITE' else (255,255,255)

            tx = rx + max(6, box//5)
            ty = ry + max(20, int(box*0.68))
            cv2.putText(canvas, ltr, (tx,ty),
                        cv2.FONT_HERSHEY_SIMPLEX, fs, tc, 2)

    # Manual mode hint
    if manual_select_mode:
        hint = "MANUAL MODE - click a cell"
        cv2.putText(canvas, hint, (ox + 4, oy + dh - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)

    return cell_rects


def draw_top_bar(canvas, sw, L, next_face, manual_mode=False, all_done=False):
    h = L['top_h']
    cv2.rectangle(canvas, (0,0), (sw, h), (18,18,18), -1)
    if manual_mode:
        txt = "MANUAL MODE  |  Click a cell on cam or cube map  |  M = exit"
        col = (0, 200, 255)
    elif next_face:
        txt = INSTRUCTIONS.get(next_face, '')
        col = (60, 255, 130)
    elif all_done:
        txt = "ALL FACES SCANNED  -  Press SOLVE  (or RANDOM MIX with a solved cube)"
        col = (60, 255, 255)
    else:
        txt = "RANDOM MIX = scramble a solved cube  |  Scan all 6 faces to SOLVE"
        col = (200, 200, 200)
    # Fixed readable font size, scale down only if text overflows
    fs = 0.52
    (tw, _), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, fs, 2)
    if tw > sw - 24:
        fs = fs * (sw - 24) / tw
    cv2.putText(canvas, txt, (12, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, fs, col, 2)


# ── Cube Net Map ──────────────────────────────────────────────────────────────
#
# Standard cube net layout (cross):
#
#           [ U ]
#  [ L ][ F ][ R ][ B ]
#           [ D ]
#
# We map each face to a grid position (col, row) in this cross.
NET_LAYOUT = {
    'U': (1, 0),
    'L': (0, 1),
    'F': (1, 1),
    'R': (2, 1),
    'B': (3, 1),
    'D': (1, 2),
}

def draw_cube_net(canvas, L, cube_state, current_face, temp_colors):
    """
    Draw an unfolded cube net in the lower-right panel area.
    Each face shows its 3×3 sticker grid (live or saved).
    Returns hit areas: dict face -> list of 9 cell rects (for manual click).
    """
    nx   = L['net_x']
    ny   = L['net_y']
    nw   = L['net_w']
    nh   = L['net_h']
    pad  = max(2, L['pad'] // 3)

    # Net is 4 cols × 3 rows of face grids
    face_cols = 4
    face_rows = 3
    margin    = pad

    face_size = min(
        (nw - margin * 2) // face_cols,
        (nh - margin * 2 - 18) // face_rows   # 18px reserved for label
    )
    face_size = max(face_size, 20)

    cell_size = face_size // 3
    gap       = 1

    # Center the net horizontally, push to top after label
    total_w = face_cols * face_size
    total_h = face_rows * face_size
    start_x = nx + (nw - total_w) // 2
    label_h = 18
    start_y = ny + label_h + (nh - total_h - label_h) // 2

    # Background
    cv2.rectangle(canvas, (nx, ny), (nx+nw, ny+nh), (14, 14, 14), -1)
    # Separator line at top
    cv2.line(canvas, (nx, ny), (nx+nw, ny), (40, 40, 40), 1)
    # Label
    cv2.putText(canvas, "CUBE MAP", (nx + pad + 2, ny + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (100, 100, 100), 1)

    net_cell_areas = {}   # face -> [(x1,y1,x2,y2), ...]

    for face, (fc, fr) in NET_LAYOUT.items():
        fx = start_x + fc * face_size
        fy = start_y + fr * face_size

        # Determine face colors to display
        saved = cube_state[face]
        if len(saved) == 9:
            colors = saved
            is_live = False
        elif face == current_face and len(temp_colors) == 9:
            colors = temp_colors
            is_live = True
        else:
            colors = ['EMPTY'] * 9
            is_live = False

        center_color = FACE_CENTER[face]
        colors = list(colors)
        colors[4] = center_color   # always show center correctly

        # Outer border: highlight current face
        is_current  = (face == current_face)
        is_complete = (len(cube_state[face]) == 9)
        if is_current:
            border_outer = (0, 210, 255)   # cyan = active face
            bthick = 2
        elif is_complete:
            border_outer = (50, 220, 70)   # green = done
            bthick = 1
        else:
            border_outer = (45, 45, 45)
            bthick = 1
        cv2.rectangle(canvas, (fx, fy), (fx+face_size-1, fy+face_size-1),
                      border_outer, bthick)

        cell_rects = []
        for row in range(3):
            for col in range(3):
                idx  = row * 3 + col
                cx1  = fx + col * cell_size + gap
                cy1  = fy + row * cell_size + gap
                cx2  = cx1 + cell_size - gap * 2
                cy2  = cy1 + cell_size - gap * 2
                cell_rects.append((cx1, cy1, cx2, cy2))

                cname = colors[idx] if idx < len(colors) else 'EMPTY'
                fill  = COLOR_BGR.get(cname, COLOR_BGR['EMPTY'])

                # Dim non-saved live colors slightly
                if is_live and idx != 4:
                    fill = tuple(int(c * 0.75) for c in fill)

                cv2.rectangle(canvas, (cx1, cy1), (cx2, cy2), fill, -1)

                # Center cell special border
                if idx == 4:
                    cv2.rectangle(canvas, (cx1, cy1), (cx2, cy2), (255,255,255), 1)

        # Face letter label — drawn inside top-left of face, with background for legibility
        fs = max(0.32, face_size / 80)
        lx = fx + 2
        ly = fy + max(11, int(face_size * 0.30))
        lc = (255, 255, 255) if not is_complete else (60, 255, 80)
        # Small dark backing rect for contrast
        (fw_, fh_), fb_ = cv2.getTextSize(face, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
        cv2.rectangle(canvas, (lx-1, ly-fh_-1), (lx+fw_+1, ly+fb_+1), (0,0,0), -1)
        cv2.putText(canvas, face, (lx, ly),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, lc, 1)

        net_cell_areas[face] = cell_rects

    return net_cell_areas


def draw_right_panel(canvas, L, cube_state, message, show_overlay, current_face):
    """
    Draw the dark right panel:
      - 6 face buttons (compacted, 2×3)
      - SOLVE | RANDOM MIX | RESET ALL buttons
      - Cube net map (live)
    Returns dict of hit-areas.
    """
    rx  = L['right_x'];  ry  = L['right_y']
    rw  = L['right_w'];  rh  = L['right_h']

    cv2.rectangle(canvas, (rx, ry), (rx+rw, ry+rh), (22,22,22), -1)
    cv2.line(canvas, (rx, ry), (rx, ry+rh), (55,55,55), 2)

    areas = {}

    # ── 6 face buttons ──
    gx   = L['grid_x'];  gy   = L['grid_y']
    bw   = L['btn_w'];   bh   = L['btn_h']
    gap  = L['btn_gap']
    fs   = max(0.38, rw / 420)

    for i, (fk, lbl, col, _) in enumerate(FACE_BUTTONS):
        col_i = i % 2
        row_i = i // 2
        bx    = gx + col_i * (bw + gap)
        by_   = gy + row_i * (bh + gap)

        saved       = len(cube_state[fk]) == 9
        is_active   = (fk == current_face)
        fill        = col if saved else (38,38,38)
        if is_active and not saved:
            fill = (50, 50, 70)   # subtle highlight for active unsaved face
        brd = (60,255,80) if saved else ((0,200,255) if is_active else (90,90,90))

        cv2.rectangle(canvas, (bx, by_), (bx+bw, by_+bh), fill, -1)
        cv2.rectangle(canvas, (bx, by_), (bx+bw, by_+bh), brd, 2)

        tc = (0,0,0) if (saved and fk=='U') else (255,255,255)

        # Face key letter (big, vertically centered)
        letter_fs = max(0.7, bh / 55)
        (lw, lh_), _ = cv2.getTextSize(fk, cv2.FONT_HERSHEY_DUPLEX, letter_fs, 2)
        cv2.putText(canvas, fk,
                    (bx + (bw - lw) // 2, by_ + int(bh * 0.60)),
                    cv2.FONT_HERSHEY_DUPLEX, letter_fs, tc, 2)
        # Colour label (bottom, readable size)
        color_fs = max(0.36, bh / 110)
        (cw_, _), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, color_fs, 1)
        cv2.putText(canvas, lbl,
                    (bx + (bw - cw_) // 2, by_ + bh - 7),
                    cv2.FONT_HERSHEY_SIMPLEX, color_fs, tc, 1)

        if saved:
            tx1 = bx + bw - 18; ty1 = by_ + 6
            cv2.putText(canvas, 'v', (tx1, ty1+12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (60,255,80), 2)

        areas[fk] = (bx, by_, bx+bw, by_+bh)

    # ── Action buttons: SOLVE | RANDOM MIX | RESET ALL ──
    all_done = all(len(cube_state[f])==9 for f in 'FRBLUD')
    ay  = L['action_y']; ah  = L['action_h']

    # SOLVE
    sx   = L['solve_x'];  sw2 = L['solve_w']
    sfill = (20,160,50) if all_done else (40,40,40)
    sbrd  = (50,255,100) if all_done else (80,80,80)
    cv2.rectangle(canvas, (sx,ay), (sx+sw2,ay+ah), sfill, -1)
    cv2.rectangle(canvas, (sx,ay), (sx+sw2,ay+ah), sbrd,  2)
    label_s = "SOLVE"
    if show_overlay and solve_state.get('mode') == 'solve':
        label_s = "SOLVING..."
    slbl_fs = 0.55
    (slw, _), _ = cv2.getTextSize(label_s, cv2.FONT_HERSHEY_SIMPLEX, slbl_fs, 2)
    cv2.putText(canvas, label_s,
                (sx + (sw2 - slw) // 2, ay + int(ah * 0.68)),
                cv2.FONT_HERSHEY_SIMPLEX, slbl_fs, (255,255,255), 2)
    areas['SOLVE'] = (sx, ay, sx+sw2, ay+ah)

    # RANDOM MIX — always enabled (assumes cube is solved, no scan required)
    mxx  = L['mix_x'];  mxw = L['mix_w']
    mfill = (140, 80, 20)
    mbrd  = (220, 160, 60)
    cv2.rectangle(canvas, (mxx,ay), (mxx+mxw,ay+ah), mfill, -1)
    cv2.rectangle(canvas, (mxx,ay), (mxx+mxw,ay+ah), mbrd,  2)
    label_m = "RANDOM MIX"
    if show_overlay and solve_state.get('mode') == 'mix':
        label_m = "MIXING..."
    m_fs = 0.46
    (mlw, _), _ = cv2.getTextSize(label_m, cv2.FONT_HERSHEY_SIMPLEX, m_fs, 1)
    while mlw > mxw - 6 and m_fs > 0.30:
        m_fs -= 0.02
        (mlw, _), _ = cv2.getTextSize(label_m, cv2.FONT_HERSHEY_SIMPLEX, m_fs, 1)
    cv2.putText(canvas, label_m,
                (mxx + (mxw - mlw) // 2, ay + int(ah * 0.68)),
                cv2.FONT_HERSHEY_SIMPLEX, m_fs, (255, 230, 200), 2)
    areas['RANDOM_MIX'] = (mxx, ay, mxx+mxw, ay+ah)

    # RESET ALL
    rax  = L['reseta_x'];  raw = L['reseta_w']
    cv2.rectangle(canvas, (rax,ay), (rax+raw,ay+ah), (10,10,130), -1)
    cv2.rectangle(canvas, (rax,ay), (rax+raw,ay+ah), (30,30,210), 2)
    rst_all_lbl = "RESET ALL"
    ra_fs = 0.46
    (ralw, _), _ = cv2.getTextSize(rst_all_lbl, cv2.FONT_HERSHEY_SIMPLEX, ra_fs, 1)
    while ralw > raw - 6 and ra_fs > 0.30:
        ra_fs -= 0.02
        (ralw, _), _ = cv2.getTextSize(rst_all_lbl, cv2.FONT_HERSHEY_SIMPLEX, ra_fs, 1)
    cv2.putText(canvas, rst_all_lbl,
                (rax + (raw - ralw) // 2, ay + int(ah * 0.68)),
                cv2.FONT_HERSHEY_SIMPLEX, ra_fs, (200, 200, 255), 1)
    areas['RESET_ALL'] = (rax, ay, rax+raw, ay+ah)

    return areas


def draw_solving_overlay(canvas, sw, sh):
    """Full-screen semi-transparent overlay for solving OR mixing."""
    ov = canvas.copy()
    cv2.rectangle(ov, (0,0), (sw,sh), (0,0,0), -1)
    cv2.addWeighted(ov, 0.75, canvas, 0.25, 0, canvas)

    cx, cy = sw//2, sh//2
    ss = solve_state
    mode = ss.get('mode', 'solve')

    # Pick status text + colour based on mode/state
    if ss['error']:
        status, scol = "ERROR", (40, 40, 230)
    elif mode == 'mix':
        if ss['done']:
            status, scol = "CUBE MIXED", (60, 200, 255)
        else:
            status, scol = "CUBE IS BEING MIXED...", (60, 200, 255)
    else:  # solve mode
        if ss['done']:
            status, scol = "CUBE SOLVED!", (60, 255, 80)
        else:
            status, scol = "CUBE IS BEING SOLVED...", (60, 230, 255)

    fsbig = max(1.0, sw/700)
    (tw,_),_ = cv2.getTextSize(status, cv2.FONT_HERSHEY_DUPLEX, fsbig, 3)
    cv2.putText(canvas, status, (cx-tw//2, cy-int(sh*0.18)),
                cv2.FONT_HERSHEY_DUPLEX, fsbig, scol, 3)

    if ss['error']:
        move_txt = ss['error'][:60]
    elif ss['total_moves'] > 0:
        move_txt = f"Move  {ss['move_index']} / {ss['total_moves']}    {ss['current_move']}"
    else:
        move_txt = ss['current_move']

    fsmid = max(0.6, sw/1000)
    (mw,_),_ = cv2.getTextSize(move_txt, cv2.FONT_HERSHEY_SIMPLEX, fsmid, 2)
    cv2.putText(canvas, move_txt, (cx-mw//2, cy),
                cv2.FONT_HERSHEY_SIMPLEX, fsmid, (230,230,230), 2)

    if ss['solution']:
        # Wrap the scramble/solution string if it's very long
        sol = ss['solution']
        fssm = max(0.38, sw/1500)
        (solw,_),_ = cv2.getTextSize(sol, cv2.FONT_HERSHEY_SIMPLEX, fssm, 1)
        # If too wide, just truncate visually
        if solw > sw * 0.9:
            # split into 2 lines
            tokens = sol.split()
            mid = len(tokens) // 2
            line1 = ' '.join(tokens[:mid])
            line2 = ' '.join(tokens[mid:])
            (w1,_),_ = cv2.getTextSize(line1, cv2.FONT_HERSHEY_SIMPLEX, fssm, 1)
            (w2,_),_ = cv2.getTextSize(line2, cv2.FONT_HERSHEY_SIMPLEX, fssm, 1)
            cv2.putText(canvas, line1, (cx-w1//2, cy+int(sh*0.08)),
                        cv2.FONT_HERSHEY_SIMPLEX, fssm, (150,150,150), 1)
            cv2.putText(canvas, line2, (cx-w2//2, cy+int(sh*0.12)),
                        cv2.FONT_HERSHEY_SIMPLEX, fssm, (150,150,150), 1)
        else:
            cv2.putText(canvas, sol, (cx-solw//2, cy+int(sh*0.09)),
                        cv2.FONT_HERSHEY_SIMPLEX, fssm, (150,150,150), 1)

    if ss['total_moves'] > 0 and not ss['error']:
        bw2  = int(sw*0.55); bh2 = max(14, int(sh*0.026))
        bx2  = cx - bw2//2;  by2 = cy + int(sh*0.18)
        prog = ss['move_index'] / ss['total_moves']
        fill = int(bw2 * prog)
        bar_col = (55,210,85) if mode == 'solve' else (60, 170, 230)
        cv2.rectangle(canvas, (bx2,by2), (bx2+bw2,by2+bh2), (45,45,45), -1)
        cv2.rectangle(canvas, (bx2,by2), (bx2+fill,by2+bh2), bar_col, -1)
        cv2.rectangle(canvas, (bx2,by2), (bx2+bw2,by2+bh2), (110,110,110), 2)
        cv2.putText(canvas, f"{int(prog*100)}%",
                    (bx2+bw2+8, by2+bh2-2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (190,190,190), 1)

    if ss['done'] or ss['error']:
        # For mix mode, the overlay is auto-dismissed after 5 seconds, so no hint
        if mode == 'mix' and not ss['error']:
            remaining = ss.get('mixed_hold_until', 0.0) - time.time()
            if remaining > 0:
                hint = f"Closing in {int(remaining)+1}s..."
            else:
                hint = ""
        else:
            hint = "Tap anywhere  or  press SPACE / X  to continue"
        if hint:
            fsh = max(0.40, sw/1600)
            (hw,_),_ = cv2.getTextSize(hint, cv2.FONT_HERSHEY_SIMPLEX, fsh, 1)
            cv2.putText(canvas, hint, (cx-hw//2, cy+int(sh*0.32)),
                        cv2.FONT_HERSHEY_COMPLEX, fsh, (170,170,170), 1)


def draw_color_picker(canvas, sw, sh, target_face, target_cell):
    """
    Draw a color picker popup centred on the screen.
    Shows 6 color swatches to choose from.
    Returns a dict: color_name -> (x1,y1,x2,y2)
    """
    # Semi-transparent overlay
    ov = canvas.copy()
    cv2.rectangle(ov, (0,0), (sw,sh), (0,0,0), -1)
    cv2.addWeighted(ov, 0.6, canvas, 0.4, 0, canvas)

    # Popup box — taller to fit 7 colors
    box_w = min(400, int(sw * 0.38))
    box_h = min(260, int(sh * 0.44))
    bx = (sw - box_w) // 2
    by = (sh - box_h) // 2

    cv2.rectangle(canvas, (bx, by), (bx+box_w, by+box_h), (30,30,30), -1)
    cv2.rectangle(canvas, (bx, by), (bx+box_w, by+box_h), (0,200,255), 2)

    title = f"Pick color for face [{target_face}]  cell {target_cell+1}"
    fs = 0.46
    (tw_, _), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
    if tw_ > box_w - 16:
        fs = fs * (box_w - 16) / tw_
    cv2.putText(canvas, title, (bx+8, by+24),
                cv2.FONT_HERSHEY_SIMPLEX, fs, (0,200,255), 1)

    swatches_per_row = 4
    n_rows = (len(ALL_COLORS) + swatches_per_row - 1) // swatches_per_row
    inner_w = box_w - 24
    inner_h = box_h - 55
    swatch_gap = 6
    swatch_size = min(
        (inner_w - (swatches_per_row - 1) * swatch_gap) // swatches_per_row,
        (inner_h - (n_rows - 1) * swatch_gap) // n_rows
    )
    sw_start_x = bx + (box_w - (swatches_per_row * swatch_size + (swatches_per_row-1)*swatch_gap)) // 2
    sw_start_y = by + 36

    picker_areas = {}
    for i, cname in enumerate(ALL_COLORS):
        col_i = i % swatches_per_row
        row_i = i // swatches_per_row
        sx1 = sw_start_x + col_i * (swatch_size + swatch_gap)
        sy1 = sw_start_y + row_i * (swatch_size + swatch_gap)
        sx2 = sx1 + swatch_size
        sy2 = sy1 + swatch_size

        fill = COLOR_BGR[cname]
        cv2.rectangle(canvas, (sx1, sy1), (sx2, sy2), fill, -1)
        brd_col = (200,200,200) if cname != 'BLACK' else (120,120,120)
        cv2.rectangle(canvas, (sx1, sy1), (sx2, sy2), brd_col, 2)

        # Color name label centered in swatch
        ltr = cname[:3]
        tc  = (0,0,0) if cname == 'WHITE' else (200,200,200) if cname == 'BLACK' else (255,255,255)
        lbl_fs = max(0.28, swatch_size / 80)
        (llw, llh), _ = cv2.getTextSize(ltr, cv2.FONT_HERSHEY_SIMPLEX, lbl_fs, 1)
        cv2.putText(canvas, ltr,
                    (sx1 + (swatch_size - llw) // 2, sy1 + (swatch_size + llh) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, lbl_fs, tc, 1)

        picker_areas[cname] = (sx1, sy1, sx2, sy2)

    # Cancel hint
    hint_y = by + box_h - 9
    cv2.putText(canvas, "ESC or click outside = cancel",
                (bx + 10, hint_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.36, (120,120,120), 1)

    return picker_areas


# ══════════════════════════════════════════
# 8. MOUSE CALLBACK
# ══════════════════════════════════════════

mouse_click = {'x':-1,'y':-1,'fired':False}

def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        mouse_click.update({'x':x,'y':y,'fired':True})

# ══════════════════════════════════════════
# 9. MAIN
# ══════════════════════════════════════════

setup_motors()

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)

WIN = 'Rubik Cube Solver'
cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
cv2.setMouseCallback(WIN, on_mouse)
SCREEN_W = 1920
SCREEN_H = 1080
print(f"[WINDOW] {SCREEN_W} x {SCREEN_H}")

L = build_layout(SCREEN_W, SCREEN_H)

cube_state   = {f:[] for f in 'FRBLUD'}
message      = "Ready!  Scan all 6 faces."
temp_colors  = []
show_overlay = False

# Manual color entry state
manual_mode         = False   # True when "M" is pressed; click cam cells to pick color
manual_select_face  = None    # which face the user is manually editing
picker_active       = False   # color picker popup open
picker_cell_idx     = None    # which cell index the picker is targeting
picker_face         = None    # which face the picker is targeting
cam_cell_rects      = []      # cell rects on camera canvas (for click detection)
net_cell_areas      = {}      # face -> cell rects on net map

print("READY | F/R/B/L/U/D = save face | M = manual color mode | SPACE = solve | N = random mix | R = reset all | Q = quit")

while True:
    ret, frame_cam = cap.read()
    if not ret:
        continue

    # ── Build canvas ──────────────────────
    canvas = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8)

    all_done = all(len(cube_state[f])==9 for f in 'FRBLUD')

    # ── Which face is next? ────────────────
    next_face = next((f for f in SCAN_ORDER if len(cube_state[f])!=9), None)
    current_face_for_display = next_face or (SCAN_ORDER[-1] if all_done else 'F')

    # Draw right panel first (background)
    areas = draw_right_panel(canvas, L, cube_state, message, show_overlay, current_face_for_display)

    # Place camera frame into left panel
    ox, oy, dw, dh = draw_camera_panel(canvas, frame_cam, L)

    # ── Live colour scan ──
    hsv = cv2.cvtColor(frame_cam, cv2.COLOR_BGR2HSV)
    cam_cx = frame_cam.shape[1] // 2
    cam_cy = frame_cam.shape[0] // 2
    box_cam  = max(28, int(frame_cam.shape[0] * 0.08))
    step_cam = max(40, int(frame_cam.shape[0] * 0.12))

    temp_colors = []
    for row, dy in enumerate((-1,0,1)):
        for col, dx in enumerate((-1,0,1)):
            idx  = row*3 + col
            rx   = cam_cx + dx*step_cam - box_cam//2
            ry_  = cam_cy + dy*step_cam - box_cam//2
            rx2  = rx + box_cam
            ry2  = ry_ + box_cam
            if idx == 4:
                temp_colors.append(FACE_CENTER.get(next_face or 'F','UNKNOWN'))
            else:
                roi = hsv[ry_:ry2, rx:rx2]
                if roi.size == 0:
                    temp_colors.append('UNKNOWN'); continue
                avg = np.mean(roi, axis=(0,1))
                temp_colors.append(color_guess(int(avg[0]),int(avg[1]),int(avg[2])))

    # ── Draw cube grid on camera ──
    cam_cell_rects = draw_cube_grid(
        canvas, frame_cam, ox, oy, dw, dh,
        next_face or 'F', temp_colors,
        cube_state.get(next_face or 'F', []),
        manual_mode
    )

    # ── Draw cube net map (live) ──
    net_cell_areas = draw_cube_net(canvas, L, cube_state, next_face or 'F', temp_colors)

    # ── Top instruction bar ────────────────
    draw_top_bar(canvas, SCREEN_W, L, next_face, manual_mode, all_done)
    if message:
        text_x = ox
        text_y = oy + dh + 40
        cv2.putText(canvas, message, (text_x, text_y), cv2.FONT_HERSHEY_DUPLEX, 0.7, (0, 210, 225), 2)

    # ── Color picker popup (drawn on top of everything) ──
    picker_areas = {}
    if picker_active:
        picker_areas = draw_color_picker(canvas, SCREEN_W, SCREEN_H,
                                         picker_face, picker_cell_idx)

    # ── Solving overlay ──
    if show_overlay:
        draw_solving_overlay(canvas, SCREEN_W, SCREEN_H)

    cv2.imshow(WIN, canvas)

    # ── Input ─────────────────────────────
    key = cv2.waitKey(1) & 0xFF

    # ─── Handle color picker clicks ───
    if picker_active:
        if mouse_click['fired']:
            mx, my = mouse_click['x'], mouse_click['y']
            mouse_click['fired'] = False
            chosen = None
            for cname, (ax1,ay1,ax2,ay2) in picker_areas.items():
                if ax1 <= mx <= ax2 and ay1 <= my <= ay2:
                    chosen = cname
                    break
            if chosen:
                # Apply color to the cell
                face  = picker_face
                cidx  = picker_cell_idx
                if cidx != 4:   # don't override center
                    saved = list(cube_state[face]) if len(cube_state[face]) == 9 else list(temp_colors)
                    if len(saved) < 9:
                        saved = ['EMPTY'] * 9
                        saved[4] = FACE_CENTER[face]
                    saved[cidx] = chosen
                    cube_state[face] = saved
                    message = f"[{face}] cell {cidx+1} set to {chosen}"
                picker_active = False
                picker_face   = None
                picker_cell_idx = None
            else:
                # Click outside picker = cancel
                picker_active = False
        if key == 27:   # ESC
            picker_active = False
        continue   # skip rest while picker open

    # ─── Handle solving/mixing overlay ───
    if show_overlay:
        mode = solve_state.get('mode', 'solve')

        # MIX overlay: auto-dismiss 5 seconds after mixing is done
        if mode == 'mix' and solve_state['done'] and not solve_state['error']:
            if time.time() >= solve_state.get('mixed_hold_until', 0.0):
                show_overlay = False
                message = "Cube mixed - press SOLVE to solve it."
                # don't consume the click/key; fall through normally
                continue
            # while waiting, ignore clicks/keys
            continue

        # SOLVE overlay (or error in either mode): dismissed by click/key
        if mouse_click['fired']:
            mouse_click['fired'] = False
            if not solve_state['running']:
                show_overlay = False
                if solve_state['done'] and mode == 'solve':
                    cube_state = {f:[] for f in 'FRBLUD'}
                    message = "Solved!  Faces reset. Scan again."
                elif solve_state['error']:
                    message = f"Error: {solve_state['error'][:55]}"
        if key in (ord(' '), ord('x'), ord('q')):
            if not solve_state['running']:
                show_overlay = False
                if solve_state['done'] and mode == 'solve':
                    cube_state = {f:[] for f in 'FRBLUD'}
                    message = "Solved!  Faces reset. Scan again."
                elif solve_state['error']:
                    message = f"Error: {solve_state['error'][:55]}"
        continue

    # ─── Normal mode ───
    clicked_face   = None
    clicked_action = None
    clicked_cam_cell = None   # index of camera grid cell clicked
    clicked_net_face = None   # face clicked in net map
    clicked_net_cell = None   # cell index in net map

    if mouse_click['fired']:
        mx, my = mouse_click['x'], mouse_click['y']
        mouse_click['fired'] = False

        # Check camera grid cells (for manual mode)
        for ci, (cx1,cy1,cx2,cy2) in enumerate(cam_cell_rects):
            if cx1 <= mx <= cx2 and cy1 <= my <= cy2:
                clicked_cam_cell = ci
                break

        # Check net map cells
        if clicked_cam_cell is None:
            for face_k, cells in net_cell_areas.items():
                for ci, (cx1,cy1,cx2,cy2) in enumerate(cells):
                    if cx1 <= mx <= cx2 and cy1 <= my <= cy2:
                        clicked_net_face = face_k
                        clicked_net_cell = ci
                        break
                if clicked_net_face:
                    break

        # Check action buttons / face buttons
        if clicked_cam_cell is None and clicked_net_face is None:
            for area_key, (ax1,ay1,ax2,ay2) in areas.items():
                if ax1<=mx<=ax2 and ay1<=my<=ay2:
                    if area_key in 'FRBLUD':
                        clicked_face = area_key
                    else:
                        clicked_action = area_key

    # ── Toggle manual mode ──
    if key == ord('m'):
        manual_mode = not manual_mode
        message = "Manual mode ON - click cells to set colors" if manual_mode else "Manual mode OFF"

    # ── Manual cell click on camera ──
    if manual_mode and clicked_cam_cell is not None and clicked_cam_cell != 4:
        face_to_edit = next_face or 'F'
        picker_active   = True
        picker_face     = face_to_edit
        picker_cell_idx = clicked_cam_cell
        continue

    # ── Manual cell click on net map ──
    if clicked_net_face is not None and clicked_net_cell is not None and clicked_net_cell != 4:
        if manual_mode or len(cube_state[clicked_net_face]) == 9:
            picker_active   = True
            picker_face     = clicked_net_face
            picker_cell_idx = clicked_net_cell
            continue

    # ── Face scan button (keyboard or button click) ──
    if key in [ord(c) for c in 'frblud']:
        clicked_face = chr(key).upper()

    if clicked_face in list('FRBLUD'):
        cs = list(temp_colors)
        cs[4] = FACE_CENTER[clicked_face]
        cube_state[clicked_face] = cs
        message = f"[{clicked_face}] face saved!"
        print(f"[SAVE {clicked_face}] {cs}")

    # ── SOLVE ──
    elif key == ord(' ') or clicked_action == 'SOLVE':
        if all(len(cube_state[f])==9 for f in 'FRBLUD'):
            show_overlay = True
            snap = {f:list(cube_state[f]) for f in 'FRBLUD'}
            threading.Thread(target=solver_thread_fn, args=(snap,), daemon=True).start()
        else:
            missing = [f for f in 'FRBLUD' if len(cube_state[f])!=9]
            message = f"Missing faces: {' '.join(missing)}"

    # ── RANDOM MIX ──
    # No scanning needed — we assume the cube is currently solved.
    # cube_state is force-set to a solved cube, then the mixer scrambles it.
    elif key == ord('n') or clicked_action == 'RANDOM_MIX':
        for f in 'FRBLUD':
            cube_state[f] = [FACE_CENTER[f]] * 9
        show_overlay = True
        # pass cube_state by reference so the mixer updates it in place
        threading.Thread(target=mixer_thread_fn, args=(cube_state, 20),
                         daemon=True).start()

    # ── RESET ALL ──
    elif key == ord('r') or clicked_action == 'RESET_ALL':
        cube_state = {f:[] for f in 'FRBLUD'}
        message = "All faces reset. Scan again."
        manual_mode = False
        print("[RESET ALL]")

    elif key == ord('q'):
        break

cap.release()
if GPIO_AVAILABLE:
    GPIO.cleanup()
cv2.destroyAllWindows()
