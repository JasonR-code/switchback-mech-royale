"""Choose horizontal gun lead from forecasts already tested on the same rival."""
from collections import deque
from math import atan2, cos, exp, hypot, sin


class GunTrack:
    def __init__(self):
        self.clear()

    def clear(self):
        self.history = deque(maxlen=16)
        self.errors = [0.] * 6
        self.weight = 0.
        self.turn = 0.
        self.drift = None
        self.velocity = None
        self.side = 0
        self.crossed_at = None
        self.periods = deque(maxlen=4)
        self.side_velocity = {}

    def _reversal(self, now, velocity, horizon, bearing):
        vx, vy = velocity
        transverse = bearing[0] * vy - bearing[1] * vx
        side = 1 if transverse > 3 else -1 if transverse < -3 else 0
        if side:
            if side != self.side:
                if self.crossed_at is not None:
                    period = now - self.crossed_at
                    if .23 < period < 3.6:
                        self.periods.append(period)
                    else:
                        self.periods.clear()
                self.crossed_at = now
                self.side = side
            ox, oy = self.side_velocity.get(side, velocity)
            self.side_velocity[side] = .7 * ox + .3 * vx, .7 * oy + .3 * vy
        if len(self.periods) < 2 or -self.side not in self.side_velocity:
            return velocity
        periods = sorted(self.periods)
        half_cycle = .5 * (periods[(len(periods)-1)//2] + periods[len(periods)//2])
        # Split the bullet flight at the next predicted sideways reversal.
        fraction = min(1., max(0., (now-self.crossed_at+horizon-half_cycle)/max(.05, horizon)))
        opposite_x, opposite_y = self.side_velocity[-self.side]
        return vx + fraction*(opposite_x-vx), vy + fraction*(opposite_y-vy)

    def step(self, now, pos, velocity, baseline, horizon, bearing):
        if self.history and not .001 < now-self.history[-1][0] < .26:
            self.clear()
        dt = now - self.history[-1][0] if self.history else .1
        vx, vy = velocity[:2]
        if self.drift is None:
            self.drift = vx, vy
        blend = 1 - exp(-dt/.5)
        self.drift = tuple(old + blend*(cur-old) for old, cur in zip(self.drift, (vx, vy)))
        omega = 0.
        if self.velocity and min(hypot(*self.velocity), hypot(vx, vy)) > 4.:
            ox, oy = self.velocity
            omega = min(3., max(-3., atan2(ox*vy-oy*vx, ox*vx+oy*vy)/dt))
        self.turn += (1-exp(-dt/.19))*(omega-self.turn)
        phi = max(-1.5, min(1.5, self.turn*horizon))
        # Average horizontal velocity along a constant-speed circular arc.
        co = sin(phi)/phi if abs(phi) > 1e-5 else 1.
        si = (1-cos(phi))/phi if abs(phi) > 1e-5 else 0.
        turn_velocity = co*vx-si*vy, si*vx+co*vy
        reversal = self._reversal(now, (vx, vy), horizon, bearing)
        forecasts = (baseline[:2], (vx, vy), (.38*vx, .38*vy), self.drift, turn_velocity, reversal)

        if self.history:
            # Score predictions only once the opponent has been observed at
            # the relevant bullet horizon. Transverse misses matter most.
            then, before, options, ray, flight = min(self.history, key=lambda s: abs(now-s[0]-s[4]))
            elapsed = now - then
            if abs(elapsed-flight) < .065:
                dx, dy = pos[0]-before[0], pos[1]-before[1]
                decay = exp(-dt/1.4)
                self.weight = decay*self.weight + 1.
                for i, (fx, fy) in enumerate(options):
                    ex, ey = fx*elapsed-dx, fy*elapsed-dy
                    cross, along = ray[0]*ey-ray[1]*ex, ray[0]*ex+ray[1]*ey
                    error = min(6., (cross*cross + .13*along*along)/6.25)
                    self.errors[i] = decay*self.errors[i] + error
        self.history.append((now, tuple(pos[:2]), forecasts, bearing, horizon))
        self.velocity = vx, vy
        best = min(range(len(self.errors)), key=self.errors.__getitem__)
        advantage = (self.errors[0] - self.errors[best])/max(1., self.weight)
        if self.weight < 3 or advantage < .065:
            return baseline
        confidence = advantage/(advantage+.12) * min(1., self.weight/6.)
        return (baseline[0]+confidence*(forecasts[best][0]-baseline[0]),
                baseline[1]+confidence*(forecasts[best][1]-baseline[1]), baseline[2])
